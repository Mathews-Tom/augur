"""Tests for manipulation signature functions and the aggregator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from augur_signals.ingestion.base import RawTrade
from augur_signals.manipulation._config import ManipulationConfig
from augur_signals.manipulation.detector import ManipulationDetector, attach_flags
from augur_signals.manipulation.episodes import CURATED_EPISODES
from augur_signals.manipulation.signatures import (
    BookEvent,
    cancel_replace_burst,
    pre_resolution_window,
    single_counterparty_concentration,
    size_vs_depth_outlier,
    thin_book_during_move,
)
from augur_signals.models import (
    ManipulationFlag,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)


def _trade(counterparty: str | None, size: float = 100.0, price: float = 0.5) -> RawTrade:
    return RawTrade(
        market_id="m",
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        price=price,
        size=size,
        side="yes",
        counterparty=counterparty,
    )


def _snapshot(liquidity: float = 5_000.0) -> MarketSnapshot:
    return MarketSnapshot(
        market_id="m",
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        last_price=0.5,
        bid=0.49,
        ask=0.51,
        spread=0.02,
        volume_24h=150_000.0,
        liquidity=liquidity,
        question="q",
        resolution_source=None,
        resolution_criteria=None,
        closes_at=None,
        raw_json={},
    )


def _signal(detected_at: datetime | None = None) -> MarketSignal:
    return MarketSignal(
        signal_id=new_signal_id(),
        market_id="m",
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.9,
        direction=1,
        confidence=0.9,
        fdr_adjusted=False,
        detected_at=detected_at or datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        raw_features={"calibration_provenance": "price_velocity_bocpd_beta_v1@identity_v0"},
    )


@pytest.mark.unit
def test_herfindahl_fully_concentrated() -> None:
    trades = [_trade("alice", 100.0), _trade("alice", 200.0)]
    assert single_counterparty_concentration(trades) == pytest.approx(1.0)


@pytest.mark.unit
def test_herfindahl_fully_dispersed() -> None:
    trades = [_trade(f"trader_{i}", 10.0) for i in range(20)]
    # Twenty equal shares => 20 * (1/20)^2 = 0.05
    assert single_counterparty_concentration(trades) == pytest.approx(0.05)


@pytest.mark.unit
def test_size_vs_depth_outlier_detects_single_large_trade() -> None:
    assert size_vs_depth_outlier(
        _trade("a", size=500.0), prior_book_depth=1000.0, threshold_ratio=0.4
    )
    assert not size_vs_depth_outlier(
        _trade("a", size=100.0), prior_book_depth=1000.0, threshold_ratio=0.4
    )


@pytest.mark.unit
def test_cancel_replace_burst_fires_when_within_window() -> None:
    base = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    events = [BookEvent("m", base + timedelta(seconds=i), "cancel", 1.0) for i in range(25)]
    assert cancel_replace_burst(events, window_seconds=60, min_count=20)


@pytest.mark.unit
def test_cancel_replace_burst_silent_when_spread_across_large_window() -> None:
    base = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    events = [BookEvent("m", base + timedelta(minutes=i), "cancel", 1.0) for i in range(25)]
    assert not cancel_replace_burst(events, window_seconds=60, min_count=20)


@pytest.mark.unit
def test_thin_book_during_move_triggers_when_median_below_floor() -> None:
    snaps = [_snapshot(liquidity=1_000.0) for _ in range(5)]
    assert thin_book_during_move(snaps, min_depth_dollars=5_000.0)


@pytest.mark.unit
def test_pre_resolution_window_excludes_far_close() -> None:
    base = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    assert pre_resolution_window(base, base + timedelta(hours=3))
    assert not pre_resolution_window(base, base + timedelta(hours=10))
    assert not pre_resolution_window(base, None)


@pytest.mark.unit
def test_manipulation_detector_attaches_flags_when_signatures_match() -> None:
    cfg = ManipulationConfig()
    det = ManipulationDetector(cfg)
    trades = [_trade("alice", 500.0)] + [_trade("alice", 500.0) for _ in range(4)]
    snapshots = [_snapshot(liquidity=500.0)]
    signal = _signal()
    flags = det.evaluate(signal, trades, [], snapshots, market_closes_at=None)
    assert ManipulationFlag.SINGLE_COUNTERPARTY_CONCENTRATION in flags
    assert ManipulationFlag.SIZE_VS_DEPTH_OUTLIER in flags
    assert ManipulationFlag.THIN_BOOK_DURING_MOVE in flags
    attached = attach_flags(signal, flags)
    assert attached.manipulation_flags == flags


@pytest.mark.unit
def test_manipulation_detector_returns_empty_when_clean() -> None:
    cfg = ManipulationConfig()
    det = ManipulationDetector(cfg)
    trades = [_trade(f"trader_{i}", 10.0) for i in range(20)]
    snapshots = [_snapshot(liquidity=50_000.0)]
    signal = _signal()
    flags = det.evaluate(signal, trades, [], snapshots, market_closes_at=None)
    assert flags == []


@pytest.mark.unit
def test_curated_episodes_list_covers_every_flag() -> None:
    seen: set[ManipulationFlag] = set()
    for episode in CURATED_EPISODES:
        seen.update(episode.expected_flags)
    assert seen == set(ManipulationFlag)
