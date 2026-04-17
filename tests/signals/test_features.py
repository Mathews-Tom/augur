"""Tests for the feature pipeline, snapshot buffer, and indicator functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from augur_signals.features._config import FeaturePipelineConfig
from augur_signals.features.indicators import (
    bid_ask_ratio,
    price_momentum,
    spread_pct,
    volatility,
    volume_ratio,
)
from augur_signals.features.pipeline import FeaturePipeline
from augur_signals.features.windows import SnapshotBuffer
from augur_signals.models import MarketSnapshot


def _snap(
    price: float = 0.5,
    volume: float = 100_000.0,
    offset_seconds: int = 0,
) -> MarketSnapshot:
    return MarketSnapshot(
        market_id="m",
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        last_price=price,
        bid=max(0.0, price - 0.01),
        ask=min(1.0, price + 0.01),
        spread=0.02,
        volume_24h=volume,
        liquidity=5000.0,
        question="q",
        resolution_source=None,
        resolution_criteria=None,
        closes_at=None,
        raw_json={},
    )


@pytest.mark.unit
def test_snapshot_buffer_appends_and_windows() -> None:
    buf = SnapshotBuffer(max_size=5)
    for i in range(8):
        buf.append(_snap(offset_seconds=i))
    # Only the last 5 snapshots are retained.
    assert len(buf) == 5
    window = buf.window(3)
    assert len(window) == 3
    assert window[-1] is buf.latest()


@pytest.mark.unit
def test_snapshot_buffer_rejects_invalid_size() -> None:
    with pytest.raises(ValueError, match="positive"):
        SnapshotBuffer(max_size=0)


@pytest.mark.unit
def test_price_momentum_zero_on_flat_window() -> None:
    window = [_snap(price=0.5, offset_seconds=i) for i in range(10)]
    assert price_momentum(window) == 0.0


@pytest.mark.unit
def test_price_momentum_positive_on_rising_window() -> None:
    window = [_snap(price=0.5 + 0.01 * i, offset_seconds=i) for i in range(10)]
    assert price_momentum(window) > 0.0


@pytest.mark.unit
def test_volatility_zero_on_flat_window() -> None:
    window = [_snap(price=0.5, offset_seconds=i) for i in range(10)]
    assert volatility(window) == 0.0


@pytest.mark.unit
def test_volatility_positive_on_oscillating_window() -> None:
    window = [
        _snap(price=0.5 + (0.05 if i % 2 == 0 else -0.05), offset_seconds=i) for i in range(20)
    ]
    assert volatility(window) > 0.0


@pytest.mark.unit
def test_volume_ratio_returns_one_when_baseline_empty() -> None:
    snaps = [_snap(volume=100.0, offset_seconds=i) for i in range(5)]
    assert volume_ratio(snaps, ewma_baseline=0.0) == 1.0


@pytest.mark.unit
def test_volume_ratio_detects_surge() -> None:
    snaps = [_snap(volume=1_000_000.0, offset_seconds=i) for i in range(5)]
    assert volume_ratio(snaps, ewma_baseline=100_000.0) == pytest.approx(10.0)


@pytest.mark.unit
def test_bid_ask_ratio_and_spread() -> None:
    snap = _snap(price=0.5)
    # bid=0.49, ask=0.51, so ratio = 0.49 / 1.0 and spread_pct = 0.02 / 0.5
    assert bid_ask_ratio(snap) == pytest.approx(0.49)
    assert spread_pct(snap) == pytest.approx(0.02 / 0.5)


@pytest.mark.unit
def test_bid_ask_ratio_returns_none_without_bid_or_ask() -> None:
    snap = _snap()
    no_bid = snap.model_copy(update={"bid": None})
    no_ask = snap.model_copy(update={"ask": None})
    assert bid_ask_ratio(no_bid) is None
    assert bid_ask_ratio(no_ask) is None


@pytest.mark.unit
def test_feature_pipeline_returns_none_during_warmup() -> None:
    cfg = FeaturePipelineConfig(warmup_size=10, buffer_size=100, ewma_alpha=0.5)
    pipeline = FeaturePipeline(cfg)
    for i in range(5):
        assert pipeline.ingest(_snap(offset_seconds=i * 30)) is None


@pytest.mark.unit
def test_feature_pipeline_emits_vector_after_warmup() -> None:
    cfg = FeaturePipelineConfig(warmup_size=5, buffer_size=50, ewma_alpha=0.5)
    pipeline = FeaturePipeline(cfg)
    last: object = None
    for i in range(10):
        last = pipeline.ingest(_snap(offset_seconds=i * 30))
    assert last is not None
    assert last.schema_version == "1.0.0"  # type: ignore[attr-defined]


@pytest.mark.unit
def test_feature_pipeline_is_idempotent_given_same_buffer() -> None:
    cfg = FeaturePipelineConfig(warmup_size=5, buffer_size=50, ewma_alpha=0.5)
    pipeline_a = FeaturePipeline(cfg)
    pipeline_b = FeaturePipeline(cfg)
    snapshots = [_snap(price=0.5 + 0.001 * i, offset_seconds=i * 30) for i in range(10)]
    vec_a = None
    vec_b = None
    for snap in snapshots:
        vec_a = pipeline_a.ingest(snap)
        vec_b = pipeline_b.ingest(snap)
    assert vec_a == vec_b
