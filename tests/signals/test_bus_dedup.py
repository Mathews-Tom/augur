"""Tests for the bus, fingerprint dedup, cluster merge, and storm controller."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from augur_signals.bus.memory import InProcessAsyncBus
from augur_signals.dedup._config import StormSettings
from augur_signals.dedup.cluster import ClusterMerge, TaxonomyEdgesProvider
from augur_signals.dedup.fingerprint import fingerprint, merge
from augur_signals.dedup.storm import StormController
from augur_signals.models import (
    ManipulationFlag,
    MarketSignal,
    SignalType,
    new_signal_id,
)


def _signal(
    market_id: str = "m",
    signal_type: SignalType = SignalType.PRICE_VELOCITY,
    offset_seconds: int = 0,
    magnitude: float = 0.8,
) -> MarketSignal:
    return MarketSignal(
        signal_id=new_signal_id(),
        market_id=market_id,
        platform="kalshi",
        signal_type=signal_type,
        magnitude=magnitude,
        direction=1,
        confidence=magnitude,
        fdr_adjusted=False,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        window_seconds=300,
        liquidity_tier="high",
        raw_features={"calibration_provenance": "detector@identity_v0"},
    )


@pytest.mark.unit
def test_fingerprint_buckets_to_same_30s_window() -> None:
    a = _signal(offset_seconds=0)
    b = _signal(offset_seconds=29)
    c = _signal(offset_seconds=31)
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint(c)


@pytest.mark.unit
def test_merge_collapses_same_fingerprint() -> None:
    a = _signal(magnitude=0.5, offset_seconds=0)
    b = _signal(magnitude=0.9, offset_seconds=20)
    # Differ in manipulation flags to check union semantics.
    b = b.model_copy(update={"manipulation_flags": [ManipulationFlag.THIN_BOOK_DURING_MOVE]})
    merged = merge([a, b])
    assert len(merged) == 1
    assert merged[0].magnitude == pytest.approx(0.9)
    assert ManipulationFlag.THIN_BOOK_DURING_MOVE in merged[0].manipulation_flags
    assert "merge_provenance" in merged[0].raw_features


@pytest.mark.unit
def test_merge_keeps_distinct_fingerprints() -> None:
    a = _signal("a", offset_seconds=0)
    b = _signal("b", offset_seconds=0)
    merged = merge([a, b])
    assert len(merged) == 2


@pytest.mark.unit
def test_cluster_merge_collapses_related_markets() -> None:
    taxonomy = TaxonomyEdgesProvider({"a": [("b", "inverse")], "b": [("a", "inverse")]})
    merger = ClusterMerge(taxonomy, window_seconds=90)
    sigs = [
        _signal("a", offset_seconds=0, magnitude=0.7),
        _signal("b", offset_seconds=30, magnitude=0.5),
    ]
    out = merger.merge(sigs)
    assert len(out) == 1
    assert "cluster_member_signal_ids" in out[0].raw_features


@pytest.mark.unit
def test_cluster_merge_skips_unrelated_markets() -> None:
    taxonomy = TaxonomyEdgesProvider({})
    merger = ClusterMerge(taxonomy, window_seconds=90)
    sigs = [_signal("a", offset_seconds=0), _signal("b", offset_seconds=30)]
    out = merger.merge(sigs)
    assert len(out) == 2


@pytest.mark.unit
def test_storm_controller_enters_and_exits() -> None:
    cfg = StormSettings(
        trigger_signal_rate_per_sec=1.0,
        trigger_signal_rate_window_sec=5,
        trigger_queue_depth_pct=0.5,
        recovery_queue_depth_pct=0.2,
        recovery_signal_rate_per_sec=0.5,
        recovery_signal_rate_window_sec=5,
        recovery_queue_depth_window_sec=1,
    )
    controller = StormController(cfg, queue_capacity=10)
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    # Push rate above trigger — should enter storm.
    state = controller.update(raw_signals_this_tick=10, queue_depth=0, now=now)
    assert state.in_storm
    # Drop to quiet; single tick is not enough (needs sustained recovery window).
    quiet = now + timedelta(seconds=6)
    controller.update(raw_signals_this_tick=0, queue_depth=0, now=quiet)
    recovered = controller.update(
        raw_signals_this_tick=0, queue_depth=0, now=quiet + timedelta(seconds=2)
    )
    assert not recovered.in_storm


@pytest.mark.asyncio
async def test_bus_publish_fans_out_to_subscribers() -> None:
    bus = InProcessAsyncBus(capacity=4)
    received: list[MarketSignal] = []

    async def consume() -> None:
        async for signal in bus.subscribe():
            received.append(signal)
            if len(received) >= 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber register
    await bus.publish(_signal(offset_seconds=0))
    await bus.publish(_signal(offset_seconds=1))
    await task
    assert len(received) == 2


@pytest.mark.unit
def test_bus_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity"):
        InProcessAsyncBus(capacity=0)
