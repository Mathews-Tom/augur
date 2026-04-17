"""Tests for the severity derivation function."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from augur_format.deterministic.severity import derive_severity
from augur_signals.models import MarketSignal, SignalType, new_signal_id


def _signal(
    magnitude: float = 0.5,
    confidence: float = 0.5,
    liquidity_tier: str = "high",
) -> MarketSignal:
    return MarketSignal(
        signal_id=new_signal_id(),
        market_id="m",
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=magnitude,
        direction=1,
        confidence=confidence,
        fdr_adjusted=True,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier=liquidity_tier,  # type: ignore[arg-type]
        raw_features={"calibration_provenance": "d@identity_v0"},
    )


@pytest.mark.unit
def test_high_tier_above_06_is_high_severity() -> None:
    assert derive_severity(_signal(magnitude=0.9, confidence=0.8)) == "high"


@pytest.mark.unit
def test_high_tier_between_03_and_06_is_medium() -> None:
    assert derive_severity(_signal(magnitude=0.6, confidence=0.6)) == "medium"


@pytest.mark.unit
def test_high_tier_at_or_below_03_is_low() -> None:
    # 0.5 * 0.6 = 0.3 → not > 0.3 → low.
    assert derive_severity(_signal(magnitude=0.5, confidence=0.6)) == "low"


@pytest.mark.unit
def test_mid_tier_above_07_is_medium() -> None:
    assert derive_severity(_signal(magnitude=0.9, confidence=0.9, liquidity_tier="mid")) == "medium"


@pytest.mark.unit
def test_mid_tier_at_or_below_07_is_low() -> None:
    assert derive_severity(_signal(magnitude=0.7, confidence=0.7, liquidity_tier="mid")) == "low"


@pytest.mark.unit
def test_low_tier_always_low_regardless_of_score() -> None:
    assert derive_severity(_signal(magnitude=1.0, confidence=1.0, liquidity_tier="low")) == "low"


@pytest.mark.unit
def test_high_tier_boundary_at_06_is_medium_not_high() -> None:
    # 0.6 * 1.0 = 0.6 → not > 0.6 → medium.
    assert derive_severity(_signal(magnitude=0.6, confidence=1.0)) == "medium"


@pytest.mark.unit
def test_derive_is_pure() -> None:
    sig = _signal(magnitude=0.9, confidence=0.9)
    first = derive_severity(sig)
    second = derive_severity(sig)
    assert first == second
