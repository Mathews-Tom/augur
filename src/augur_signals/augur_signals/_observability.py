"""Observability primitives: metric counters, gauges, and trace spans.

The implementations here are deliberate no-ops. Call sites instrument
code with counters, gauges, and spans against these shims; the
multi-process runtime replaces the shims with real Prometheus and
OpenTelemetry adapters without any call-site edits.

The shim approach keeps signal-extraction, labeling, and formatter code
free of a hard dependency on the observability backend during early
development and testing, while still exercising the instrumentation
surface end-to-end.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any


class MetricCounter:
    """No-op counter shim.

    Attributes:
        name: Metric name in the Prometheus namespace.
        labels: Label-key list; values are supplied at ``inc`` time.
    """

    def __init__(self, name: str, labels: list[str]) -> None:
        self.name = name
        self.labels = list(labels)

    def inc(self, value: float = 1.0, **label_values: str) -> None:
        """Increment the counter. No-op in the shim implementation."""
        _ = value, label_values


class MetricGauge:
    """No-op gauge shim.

    Attributes:
        name: Metric name in the Prometheus namespace.
        labels: Label-key list; values are supplied at ``set`` time.
    """

    def __init__(self, name: str, labels: list[str]) -> None:
        self.name = name
        self.labels = list(labels)

    def set(self, value: float, **label_values: str) -> None:
        """Set the gauge. No-op in the shim implementation."""
        _ = value, label_values


@contextmanager
def trace_span(name: str, **attributes: Any) -> Generator[None, None, None]:
    """No-op trace-span shim.

    The real implementation will open an OpenTelemetry span, attach
    *attributes*, and close it on context exit. For now, the call site
    is exercised but no data is recorded.
    """
    _ = name, attributes
    yield
