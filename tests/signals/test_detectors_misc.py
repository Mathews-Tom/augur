"""Tests for volume-spike, book-imbalance, and regime-shift detectors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from augur_signals.detectors._config import (
    BookImbalanceConfig,
    RegimeShiftConfig,
    VolumeSpikeConfig,
)
from augur_signals.detectors.book_imbalance import BookImbalanceDetector
from augur_signals.detectors.regime_shift import RegimeShiftDetector
from augur_signals.detectors.volume_spike import VolumeSpikeDetector
from augur_signals.models import FeatureVector, MarketSnapshot


def _fv(
    volume_ratio_1h: float = 1.0, bid_ask_ratio: float | None = 0.5, vol_1h: float = 0.02
) -> FeatureVector:
    return FeatureVector(
        market_id="m",
        computed_at=datetime(2026, 3, 15, tzinfo=UTC),
        price_momentum_5m=0.0,
        price_momentum_15m=0.0,
        price_momentum_1h=0.0,
        price_momentum_4h=0.0,
        volatility_5m=vol_1h,
        volatility_15m=vol_1h,
        volatility_1h=vol_1h,
        volatility_4h=vol_1h,
        volume_ratio_5m=volume_ratio_1h,
        volume_ratio_1h=volume_ratio_1h,
        bid_ask_ratio=bid_ask_ratio,
        spread_pct=0.01,
    )


def _snap(
    liquidity: float = 20_000.0,
    volume_24h: float = 200_000.0,
    closes_at: datetime | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        market_id="m",
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, tzinfo=UTC),
        last_price=0.5,
        bid=0.49,
        ask=0.51,
        spread=0.02,
        volume_24h=volume_24h,
        liquidity=liquidity,
        question="q",
        resolution_source=None,
        resolution_criteria=None,
        closes_at=closes_at,
        raw_json={},
    )


@pytest.mark.unit
def test_volume_spike_fires_on_sustained_high_ratio() -> None:
    cfg = VolumeSpikeConfig(ewma_alpha=0.2, minimum_z=1.0)
    det = VolumeSpikeDetector(cfg)
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    # Warmup phase with stable ratio.
    for i in range(30):
        det.ingest("m", _fv(volume_ratio_1h=1.0), _snap(), now + timedelta(seconds=i * 30))
    # Sudden surge.
    sig = det.ingest("m", _fv(volume_ratio_1h=3.0), _snap(), now + timedelta(seconds=30 * 30))
    assert sig is not None
    assert sig.signal_type.value == "volume_spike"
    assert sig.raw_features["z_score"] > cfg.minimum_z


@pytest.mark.unit
def test_volume_spike_silent_below_absolute_floor() -> None:
    det = VolumeSpikeDetector(VolumeSpikeConfig(min_absolute_volume=1_000_000))
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    for i in range(50):
        sig = det.ingest(
            "m",
            _fv(volume_ratio_1h=5.0),
            _snap(volume_24h=100.0),
            now + timedelta(seconds=i * 30),
        )
        assert sig is None


@pytest.mark.unit
def test_book_imbalance_requires_persistence() -> None:
    cfg = BookImbalanceConfig(persistence_snapshots=3, minimum_total_depth=5_000.0)
    det = BookImbalanceDetector(cfg)
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    for i in range(2):
        sig = det.ingest("m", _fv(bid_ask_ratio=0.8), _snap(), now + timedelta(seconds=i * 30))
        assert sig is None
    sig = det.ingest("m", _fv(bid_ask_ratio=0.8), _snap(), now + timedelta(seconds=3 * 30))
    assert sig is not None
    assert sig.direction == 1


@pytest.mark.unit
def test_book_imbalance_silent_on_thin_book() -> None:
    cfg = BookImbalanceConfig(persistence_snapshots=2, minimum_total_depth=10_000.0)
    det = BookImbalanceDetector(cfg)
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    for i in range(5):
        assert (
            det.ingest(
                "m",
                _fv(bid_ask_ratio=0.9),
                _snap(liquidity=1_000.0),
                now + timedelta(seconds=i * 30),
            )
            is None
        )


@pytest.mark.unit
def test_book_imbalance_resets_on_mid_band() -> None:
    cfg = BookImbalanceConfig(persistence_snapshots=3, minimum_total_depth=1_000.0)
    det = BookImbalanceDetector(cfg)
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    det.ingest("m", _fv(bid_ask_ratio=0.85), _snap(), now)
    det.ingest("m", _fv(bid_ask_ratio=0.5), _snap(), now + timedelta(seconds=30))
    det.ingest("m", _fv(bid_ask_ratio=0.85), _snap(), now + timedelta(seconds=60))
    sig = det.ingest("m", _fv(bid_ask_ratio=0.85), _snap(), now + timedelta(seconds=90))
    # After the mid reset, only two bullish ticks in a row — below persistence.
    assert sig is None


@pytest.mark.unit
def test_regime_shift_waits_for_dormancy_then_fires() -> None:
    cfg = RegimeShiftConfig(dormancy_minimum_seconds=600, k_multiplier=0.1, h_multiplier=0.5)
    det = RegimeShiftDetector(cfg)
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    # Warmup quiet, slowly changing volatility.
    for i in range(40):
        det.ingest(
            "m",
            _fv(vol_1h=0.01),
            _snap(),
            now + timedelta(seconds=i * 30),
        )
    # Wait for dormancy window to pass without a crossing.
    later = now + timedelta(seconds=600)
    # Large shift.
    sig = None
    for i in range(20):
        sig = det.ingest(
            "m",
            _fv(vol_1h=0.20),
            _snap(),
            later + timedelta(seconds=i * 30),
        )
        if sig is not None:
            break
    assert sig is not None
    assert sig.signal_type.value == "regime_shift"


@pytest.mark.unit
def test_regime_shift_silent_during_pre_resolution_window() -> None:
    cfg = RegimeShiftConfig(dormancy_minimum_seconds=60)
    det = RegimeShiftDetector(cfg)
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    closes = now + timedelta(hours=1)
    for _ in range(40):
        assert det.ingest("m", _fv(vol_1h=1.0), _snap(closes_at=closes), now) is None
