"""Tests for BH-FDR, reliability curves, drift monitor, and cross-market divergence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from augur_signals.calibration._config import CalibrationConfig
from augur_signals.calibration.drift_monitor import DriftMonitor
from augur_signals.calibration.empirical_fpr import compute_empirical_fpr
from augur_signals.calibration.fdr_controller import (
    FDRController,
    benjamini_hochberg,
)
from augur_signals.calibration.liquidity_tier import banding
from augur_signals.calibration.reliability import (
    ReliabilityAnalyzer,
    build_identity_curve,
)
from augur_signals.detectors._config import CrossMarketConfig
from augur_signals.detectors.cross_market import (
    CrossMarketDivergenceDetector,
    RelatedMarketPair,
)
from augur_signals.models import MarketSnapshot


def _snap(price: float, market_id: str = "m", volume_24h: float = 200_000.0) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, tzinfo=UTC),
        last_price=price,
        bid=max(0.0, price - 0.01),
        ask=min(1.0, price + 0.01),
        spread=0.02,
        volume_24h=volume_24h,
        liquidity=5000.0,
        question="q",
        resolution_source=None,
        resolution_criteria=None,
        closes_at=None,
        raw_json={},
    )


@pytest.mark.unit
def test_benjamini_hochberg_accepts_small_pvalues() -> None:
    mask = benjamini_hochberg([0.001, 0.01, 0.2, 0.9], q=0.05)
    assert mask == [True, True, False, False]


@pytest.mark.unit
def test_benjamini_hochberg_returns_empty_on_no_input() -> None:
    assert benjamini_hochberg([], q=0.05) == []


@pytest.mark.unit
def test_benjamini_hochberg_validates_q() -> None:
    with pytest.raises(ValueError, match="FDR q"):
        benjamini_hochberg([0.01], q=0.0)


@pytest.mark.unit
def test_fdr_controller_returns_signal_ids_that_pass() -> None:
    controller = FDRController(CalibrationConfig(target_fdr_q=0.05))
    accepted = controller.submit_pvalues("any_detector", [("s1", 0.001), ("s2", 0.04), ("s3", 0.6)])
    assert "s1" in accepted
    assert "s3" not in accepted


@pytest.mark.unit
def test_reliability_identity_curve_is_monotone() -> None:
    analyzer = ReliabilityAnalyzer()
    assert analyzer.calibrate("d", "high", 0.1) == pytest.approx(0.1)
    assert analyzer.calibrate("d", "high", 0.9) == pytest.approx(0.9)
    assert analyzer.curve_version("d", "high") == "identity_v0"


@pytest.mark.unit
def test_reliability_registered_curve_interpolates() -> None:
    curve = build_identity_curve("d", "mid")
    analyzer = ReliabilityAnalyzer()
    analyzer.register_curve(curve)
    assert analyzer.curve_version("d", "mid") == "identity_v0"
    assert analyzer.calibrate("d", "mid", 0.25) == pytest.approx(0.25)


@pytest.mark.unit
def test_liquidity_banding_crosses_thresholds() -> None:
    assert banding(500_000) == "high"
    assert banding(100_000) == "mid"
    assert banding(10_000) == "low"


@pytest.mark.unit
def test_empirical_fpr_identifies_true_positives() -> None:
    signals = [datetime(2026, 3, 15, 12, 0, tzinfo=UTC)]
    events = [datetime(2026, 3, 15, 14, 0, tzinfo=UTC)]
    record = compute_empirical_fpr(
        "d",
        "m",
        signals,
        events,
        lead_window=timedelta(hours=24),
    )
    assert record.fpr == pytest.approx(0.0)
    assert record.sample_size == 1


@pytest.mark.unit
def test_empirical_fpr_flags_unlabeled_signals() -> None:
    signals = [datetime(2026, 3, 15, 12, 0, tzinfo=UTC)]
    events: list[datetime] = []
    record = compute_empirical_fpr("d", "m", signals, events, lead_window=timedelta(hours=24))
    assert record.fpr == pytest.approx(1.0)


@pytest.mark.unit
def test_drift_monitor_triggers_on_distribution_shift() -> None:
    monitor = DriftMonitor(CalibrationConfig(psi_trigger_threshold=0.1))
    baseline = [0.1] * 100 + [0.2] * 100
    current = [0.8] * 100 + [0.9] * 100
    report = monitor.check("d", baseline, current, datetime(2026, 3, 15, tzinfo=UTC))
    assert report.triggered
    assert "psi" in report.triggered_metrics or "ks" in report.triggered_metrics


@pytest.mark.unit
def test_drift_monitor_silent_on_stable_distribution() -> None:
    monitor = DriftMonitor(CalibrationConfig())
    baseline = [0.4, 0.5, 0.6] * 50
    current = [0.4, 0.5, 0.6] * 50
    report = monitor.check("d", baseline, current, datetime(2026, 3, 15, tzinfo=UTC))
    assert not report.triggered


@pytest.mark.unit
def test_cross_market_divergence_fires_on_decorrelation() -> None:
    cfg = CrossMarketConfig(window_seconds=300, target_fdr_q=0.1)
    fdr = FDRController(CalibrationConfig(target_fdr_q=0.1))
    pair = RelatedMarketPair(market_a="a", market_b="b", historical_z=2.0)
    det = CrossMarketDivergenceDetector(cfg, fdr, [pair])
    now = datetime(2026, 3, 15, tzinfo=UTC)
    # Build a history where a and b are anti-correlated (fisher_z small/negative).
    for i in range(15):
        det.evaluate_batch(
            {
                "a": _snap(0.1 + 0.01 * (i % 2), "a"),
                "b": _snap(0.9 - 0.01 * (i % 2), "b"),
            },
            now + timedelta(seconds=i * 10),
        )
    signals = det.evaluate_batch(
        {"a": _snap(0.1, "a"), "b": _snap(0.9, "b")},
        now + timedelta(seconds=200),
    )
    assert any(sig.signal_type.value == "cross_market_divergence" for sig in signals)
