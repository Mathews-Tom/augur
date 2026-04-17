"""Tests for the observability primitives and backend wiring."""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from augur_signals._observability import (
    MetricCounter,
    MetricGauge,
    configure_observability,
    trace_span,
)
from augur_signals._observability_config import (
    LogsBody,
    MetricsBody,
    ObservabilityConfig,
    TracesBody,
)


@pytest.fixture
def registry() -> CollectorRegistry:
    """Per-test registry so counters do not collide across cases."""
    reg = CollectorRegistry()
    configure_observability(
        ObservabilityConfig(
            metrics=MetricsBody(kind="disabled"),
            traces=TracesBody(kind="disabled"),
            logs=LogsBody(),
        ),
        reg,
    )
    return reg


@pytest.fixture(autouse=True)
def _reset_default() -> None:
    """Reset to disabled backend when a test does not claim the registry."""
    configure_observability(
        ObservabilityConfig(
            metrics=MetricsBody(kind="disabled"),
            traces=TracesBody(kind="disabled"),
            logs=LogsBody(),
        )
    )


@pytest.mark.unit
def test_metric_counter_instantiates_and_increments() -> None:
    counter = MetricCounter("signals_emitted_total", ["detector_id", "market_id"])
    assert counter.name == "signals_emitted_total"
    assert counter.labels == ["detector_id", "market_id"]
    counter.inc()
    counter.inc(2.0, detector_id="price_velocity", market_id="m-1")


@pytest.mark.unit
def test_metric_gauge_instantiates_and_sets() -> None:
    gauge = MetricGauge("bus_queue_depth", ["tier"])
    assert gauge.name == "bus_queue_depth"
    assert gauge.labels == ["tier"]
    gauge.set(42.0)
    gauge.set(0.0, tier="hot")


@pytest.mark.unit
def test_trace_span_is_a_context_manager() -> None:
    with trace_span("ingest_tick", market_id="m-1"):
        captured = "inside"
    assert captured == "inside"


@pytest.mark.unit
def test_trace_span_with_no_attributes() -> None:
    with trace_span("noop"):
        pass


@pytest.mark.unit
def test_prometheus_backend_records_increments(registry: CollectorRegistry) -> None:
    configure_observability(
        ObservabilityConfig(
            metrics=MetricsBody(kind="prometheus"),
            traces=TracesBody(kind="disabled"),
            logs=LogsBody(),
        ),
        registry,
    )
    counter = MetricCounter("augur_worker_processed_total", ["worker_kind"])
    counter.inc(3.0, worker_kind="feature")
    counter.inc(worker_kind="feature")
    payload = generate_latest(registry).decode("utf-8")
    assert 'augur_worker_processed_total{worker_kind="feature"} 4.0' in payload


@pytest.mark.unit
def test_prometheus_gauge_overwrites_value(registry: CollectorRegistry) -> None:
    configure_observability(
        ObservabilityConfig(
            metrics=MetricsBody(kind="prometheus"),
            traces=TracesBody(kind="disabled"),
            logs=LogsBody(),
        ),
        registry,
    )
    gauge = MetricGauge("augur_bus_queue_depth", ["topic"])
    gauge.set(10.0, topic="augur.signals")
    gauge.set(3.0, topic="augur.signals")
    payload = generate_latest(registry).decode("utf-8")
    assert 'augur_bus_queue_depth{topic="augur.signals"} 3.0' in payload


@pytest.mark.unit
def test_counter_singleton_across_instantiations(registry: CollectorRegistry) -> None:
    configure_observability(
        ObservabilityConfig(
            metrics=MetricsBody(kind="prometheus"),
            traces=TracesBody(kind="disabled"),
            logs=LogsBody(),
        ),
        registry,
    )
    first = MetricCounter("augur_failover_total", ["singleton_kind"])
    second = MetricCounter("augur_failover_total", ["singleton_kind"])
    first.inc(singleton_kind="dedup")
    second.inc(singleton_kind="dedup")
    payload = generate_latest(registry).decode("utf-8")
    assert 'augur_failover_total{singleton_kind="dedup"} 2.0' in payload
