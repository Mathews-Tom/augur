"""Tests for the observability shim primitives."""

from __future__ import annotations

import pytest

from augur_signals._observability import MetricCounter, MetricGauge, trace_span


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
