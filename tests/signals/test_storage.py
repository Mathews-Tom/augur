"""Tests for the DuckDB storage layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from augur_signals.models import (
    FeatureVector,
    ManipulationFlag,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)
from augur_signals.storage.duckdb_store import DuckDBStore


def _snapshot(market_id: str = "m", offset: int = 0) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC) + timedelta(seconds=offset),
        last_price=0.5,
        bid=0.49,
        ask=0.51,
        spread=0.02,
        volume_24h=150_000.0,
        liquidity=5_000.0,
        question="Q",
        resolution_source="Source",
        resolution_criteria="Criteria",
        closes_at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        raw_json={"raw": 1},
    )


def _signal(market_id: str = "m", offset: int = 0) -> MarketSignal:
    return MarketSignal(
        signal_id=new_signal_id(),
        market_id=market_id,
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.8,
        direction=1,
        confidence=0.75,
        fdr_adjusted=False,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC) + timedelta(seconds=offset),
        window_seconds=300,
        liquidity_tier="high",
        manipulation_flags=[ManipulationFlag.SIZE_VS_DEPTH_OUTLIER],
        raw_features={"calibration_provenance": "price_velocity_bocpd_beta_v1@identity_v0"},
    )


@pytest.fixture
def store(tmp_path: Path) -> DuckDBStore:
    s = DuckDBStore(tmp_path / "augur.duckdb")
    s.initialize()
    yield s
    s.close()


@pytest.mark.unit
def test_initialize_is_idempotent(tmp_path: Path) -> None:
    s1 = DuckDBStore(tmp_path / "augur.duckdb")
    s1.initialize()
    s1.close()
    s2 = DuckDBStore(tmp_path / "augur.duckdb")
    s2.initialize()
    s2.close()  # No exception means idempotent.


@pytest.mark.unit
def test_insert_snapshot_round_trips(store: DuckDBStore) -> None:
    snap = _snapshot()
    store.insert_snapshot(snap)
    latest = store.latest_snapshot("m")
    assert latest is not None
    assert latest.last_price == snap.last_price
    assert latest.raw_json == snap.raw_json


@pytest.mark.unit
def test_snapshots_in_window(store: DuckDBStore) -> None:
    for i in range(5):
        store.insert_snapshot(_snapshot(offset=i * 60))
    start = datetime(2026, 3, 15, 12, 0, 30, tzinfo=UTC)
    end = datetime(2026, 3, 15, 12, 3, 30, tzinfo=UTC)
    rows = store.snapshots_in_window("m", start, end)
    assert len(rows) == 3


@pytest.mark.unit
def test_insert_signal_round_trips_manipulation_flags(store: DuckDBStore) -> None:
    sig = _signal()
    store.insert_signal(sig)
    recovered = store.signals_in_window(
        ["m"],
        datetime(2026, 3, 15, 11, 0, tzinfo=UTC),
        datetime(2026, 3, 15, 13, 0, tzinfo=UTC),
    )
    assert len(recovered) == 1
    assert recovered[0].signal_id == sig.signal_id
    assert recovered[0].confidence == pytest.approx(0.75)
    # Flags persist to the side table and rehydrate on read so backtest
    # code sees the same flag set a consumer received at publish time.
    assert recovered[0].manipulation_flags == sig.manipulation_flags


@pytest.mark.unit
def test_insert_feature_round_trips(store: DuckDBStore) -> None:
    fv = FeatureVector(
        market_id="m",
        computed_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        price_momentum_5m=0.01,
        price_momentum_15m=0.02,
        price_momentum_1h=0.03,
        price_momentum_4h=0.04,
        volatility_5m=0.01,
        volatility_15m=0.02,
        volatility_1h=0.03,
        volatility_4h=0.04,
        volume_ratio_5m=1.1,
        volume_ratio_1h=1.2,
        bid_ask_ratio=0.5,
        spread_pct=0.02,
    )
    store.insert_feature(fv)  # Just verify no exception; read-side not exposed yet.


@pytest.mark.unit
def test_latest_snapshot_returns_none_when_empty(store: DuckDBStore) -> None:
    assert store.latest_snapshot("missing") is None
