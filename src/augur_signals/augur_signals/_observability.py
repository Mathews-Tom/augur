"""Observability primitives: metric counters, gauges, and trace spans.

This module exposes `MetricCounter`, `MetricGauge`, and
`trace_span`. Call sites build an instance by name+labels and invoke
`inc` / `set` / `with trace_span(...)`; the concrete backend is
swapped via `configure_observability` without touching instrumented
code. Three backend combinations are supported:

* disabled — no-op shims. The Phase 1 default; suitable for unit tests
  and backtest runs where metric emission would pollute signal.
* prometheus + otlp — the Phase 5 deployment. Metrics land in the
  prometheus_client default registry and a /metrics HTTP endpoint is
  started via `start_metrics_server`. Traces route through an
  OpenTelemetry `TracerProvider` with OTLP export.
* mixed — independent knobs per surface (metrics disabled, traces on;
  or vice versa) for incremental rollout.

The backend is a module-global singleton because prometheus_client and
the OpenTelemetry SDK both maintain their own global state. Calling
`configure_observability` a second time rebuilds the backend and
replaces previously-registered collectors; this is only safe in tests.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Protocol

from augur_signals._observability_config import ObservabilityConfig

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry


class _CounterBackend(Protocol):
    def inc(self, value: float, label_values: dict[str, str]) -> None: ...


class _GaugeBackend(Protocol):
    def set(self, value: float, label_values: dict[str, str]) -> None: ...


class _TracerBackend(Protocol):
    @contextmanager
    def span(self, name: str, attributes: dict[str, Any]) -> Generator[None, None, None]: ...


class _NoOpCounter:
    def inc(self, value: float, label_values: dict[str, str]) -> None:
        _ = value, label_values


class _NoOpGauge:
    def set(self, value: float, label_values: dict[str, str]) -> None:
        _ = value, label_values


class _NoOpTracer:
    @contextmanager
    def span(self, name: str, attributes: dict[str, Any]) -> Generator[None, None, None]:
        _ = name, attributes
        yield


class _PromCounter:
    def __init__(self, name: str, labels: list[str], registry: CollectorRegistry | None) -> None:
        from prometheus_client import Counter

        self._counter = Counter(name, name, labels, registry=registry)
        self._labels = labels

    def inc(self, value: float, label_values: dict[str, str]) -> None:
        if self._labels:
            self._counter.labels(**{k: label_values.get(k, "") for k in self._labels}).inc(value)
        else:
            self._counter.inc(value)


class _PromGauge:
    def __init__(self, name: str, labels: list[str], registry: CollectorRegistry | None) -> None:
        from prometheus_client import Gauge

        self._gauge = Gauge(name, name, labels, registry=registry)
        self._labels = labels

    def set(self, value: float, label_values: dict[str, str]) -> None:
        if self._labels:
            self._gauge.labels(**{k: label_values.get(k, "") for k in self._labels}).set(value)
        else:
            self._gauge.set(value)


class _OTelTracer:
    def __init__(self, service_name: str, endpoint: str, sampling_ratio: float) -> None:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        # OTel refuses to replace the global TracerProvider once set
        # and logs a silent "Overriding" warning. Reuse an existing
        # provider on re-configuration (common across test cases)
        # rather than fighting the SDK's global state.
        current = trace.get_tracer_provider()
        if isinstance(current, TracerProvider):
            self._tracer = trace.get_tracer("augur")
            return
        resource = Resource.create({SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource, sampler=TraceIdRatioBased(sampling_ratio))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer("augur")

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any]) -> Generator[None, None, None]:
        with self._tracer.start_as_current_span(name, attributes=attributes):
            yield


class _Backend:
    """Module-level backend selector.

    Holds factory callables so `MetricCounter("foo", [...])` can be
    built after configuration without rebuilding the class hierarchy.
    """

    def __init__(self) -> None:
        self._metrics_kind: str = "disabled"
        self._registry: CollectorRegistry | None = None
        self._tracer: _TracerBackend = _NoOpTracer()
        self._lock = threading.Lock()
        self._counters: dict[str, _CounterBackend] = {}
        self._gauges: dict[str, _GaugeBackend] = {}

    def configure(
        self,
        config: ObservabilityConfig,
        registry: CollectorRegistry | None = None,
    ) -> None:
        with self._lock:
            self._metrics_kind = config.metrics.kind
            self._registry = registry
            self._counters.clear()
            self._gauges.clear()
            if config.traces.kind == "otlp":
                self._tracer = _OTelTracer(
                    config.traces.service_name,
                    config.traces.otlp_endpoint,
                    config.traces.sampling_ratio,
                )
            else:
                self._tracer = _NoOpTracer()

    def counter(self, name: str, labels: list[str]) -> _CounterBackend:
        with self._lock:
            existing = self._counters.get(name)
            if existing is not None:
                return existing
            backend: _CounterBackend = (
                _PromCounter(name, labels, self._registry)
                if self._metrics_kind == "prometheus"
                else _NoOpCounter()
            )
            self._counters[name] = backend
            return backend

    def gauge(self, name: str, labels: list[str]) -> _GaugeBackend:
        with self._lock:
            existing = self._gauges.get(name)
            if existing is not None:
                return existing
            backend: _GaugeBackend = (
                _PromGauge(name, labels, self._registry)
                if self._metrics_kind == "prometheus"
                else _NoOpGauge()
            )
            self._gauges[name] = backend
            return backend

    def tracer(self) -> _TracerBackend:
        return self._tracer


_BACKEND = _Backend()


def configure_observability(
    config: ObservabilityConfig,
    registry: CollectorRegistry | None = None,
) -> None:
    """Activate real backends per *config*.

    *registry* is the prometheus_client `CollectorRegistry` the
    backend registers counters and gauges with. Production leaves it
    `None` so the default module-level registry is used; tests pass
    a fresh `CollectorRegistry()` to isolate collectors between
    cases.

    Leaves counters and gauges unregistered until their first
    `MetricCounter(name, labels)` / `MetricGauge(name, labels)` call
    so test suites can re-configure without colliding on the shared
    prometheus_client registry.
    """
    _BACKEND.configure(config, registry)


def start_metrics_server(config: ObservabilityConfig) -> None:
    """Start a /metrics HTTP listener on the configured bind/port.

    Separate from `configure_observability` because the backtest
    harness configures the backend without ever binding a port.
    """
    if config.metrics.kind != "prometheus":
        return
    from prometheus_client import start_http_server

    start_http_server(config.metrics.prometheus_port, addr=config.metrics.prometheus_bind)


class MetricCounter:
    """Monotonic counter. Call `inc` to increment.

    Attributes:
        name: Metric name exposed to the scraper.
        labels: Ordered list of label keys; values are provided at
            `inc` time via keyword arguments.
    """

    def __init__(self, name: str, labels: list[str]) -> None:
        self.name = name
        self.labels = list(labels)
        self._backend = _BACKEND.counter(name, self.labels)

    def inc(self, value: float = 1.0, **label_values: str | int | float) -> None:
        """Increment by *value*; label values are stringified on the way in."""
        self._backend.inc(value, {k: str(v) for k, v in label_values.items()})


class MetricGauge:
    """Instantaneous value. Call `set` to overwrite.

    Attributes:
        name: Metric name exposed to the scraper.
        labels: Ordered list of label keys; values are provided at
            `set` time via keyword arguments.
    """

    def __init__(self, name: str, labels: list[str]) -> None:
        self.name = name
        self.labels = list(labels)
        self._backend = _BACKEND.gauge(name, self.labels)

    def set(self, value: float, **label_values: str | int | float) -> None:
        """Set the gauge to *value*; label values are stringified."""
        self._backend.set(value, {k: str(v) for k, v in label_values.items()})


@contextmanager
def trace_span(name: str, **attributes: Any) -> Generator[None, None, None]:
    """Open a trace span named *name* with *attributes*; auto-close on exit."""
    with _BACKEND.tracer().span(name, dict(attributes)):
        yield
