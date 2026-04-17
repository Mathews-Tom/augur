"""Tests for the price-velocity detector and Beta-Binomial BOCPD.

Covers the algorithmic invariants listed in phase-1 §15.2: constant
streams produce no signal, step changes fire within the first 50
observations after the change, boundary prices do not crash the
detector, and the pre-resolution exclusion window is honored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from augur_signals.detectors._bocpd import BetaBinomialBOCPD
from augur_signals.detectors._config import PriceVelocityConfig
from augur_signals.detectors.price_velocity import PriceVelocityDetector
from augur_signals.models import FeatureVector, MarketSnapshot


def _fv() -> FeatureVector:
    return FeatureVector(
        market_id="m",
        computed_at=datetime(2026, 3, 15, tzinfo=UTC),
        price_momentum_5m=0.0,
        price_momentum_15m=0.0,
        price_momentum_1h=0.0,
        price_momentum_4h=0.0,
        volatility_5m=0.0,
        volatility_15m=0.0,
        volatility_1h=0.0,
        volatility_4h=0.0,
        volume_ratio_5m=1.0,
        volume_ratio_1h=1.0,
        bid_ask_ratio=0.5,
        spread_pct=0.01,
    )


def _snap(price: float, closes_at: datetime | None = None) -> MarketSnapshot:
    return MarketSnapshot(
        market_id="m",
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        last_price=price,
        bid=max(0.0, price - 0.01),
        ask=min(1.0, price + 0.01),
        spread=0.02,
        volume_24h=120_000.0,
        liquidity=5_000.0,
        question="q",
        resolution_source=None,
        resolution_criteria=None,
        closes_at=closes_at,
        raw_json={},
    )


@pytest.mark.unit
def test_bocpd_rejects_out_of_range_observation() -> None:
    bocpd = BetaBinomialBOCPD(hazard_rate=0.01, alpha_prior=1.0, beta_prior=1.0, run_length_cap=50)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        bocpd.update(-0.5)


@pytest.mark.unit
def test_bocpd_constants_do_not_trigger_change() -> None:
    bocpd = BetaBinomialBOCPD(
        hazard_rate=0.004, alpha_prior=1.0, beta_prior=1.0, run_length_cap=200
    )
    p_change = 1.0
    for _ in range(400):
        p_change, _ = bocpd.update(0.5)
    # After a long constant stream, P(r_t < 5) should be small.
    assert p_change < 0.3


@pytest.mark.unit
def test_bocpd_detects_step_change() -> None:
    # Binary-projected observations (all zeros before the shift, all ones after)
    # drive the Beta-Binomial posterior onto a sharp edge; P(r_t < 5) should
    # rise above the fire threshold within the first handful of observations.
    bocpd = BetaBinomialBOCPD(hazard_rate=0.01, alpha_prior=1.0, beta_prior=1.0, run_length_cap=200)
    for _ in range(100):
        bocpd.update(0.0)
    fired = False
    for _ in range(50):
        p_change, _ = bocpd.update(1.0)
        if p_change > 0.7:
            fired = True
            break
    assert fired


@pytest.mark.unit
def test_price_velocity_no_signal_on_flat_stream() -> None:
    detector = PriceVelocityDetector(PriceVelocityConfig())
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    emitted = [
        detector.ingest("m", _fv(), _snap(0.5), now + timedelta(seconds=i * 30)) for i in range(200)
    ]
    assert all(sig is None for sig in emitted)


@pytest.mark.unit
def test_price_velocity_no_signal_during_pre_resolution_window() -> None:
    detector = PriceVelocityDetector(PriceVelocityConfig())
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    closes_at = now + timedelta(hours=2)  # inside the 6h exclusion window
    assert detector.ingest("m", _fv(), _snap(0.5, closes_at), now) is None


@pytest.mark.unit
def test_price_velocity_boundary_prices_do_not_crash() -> None:
    detector = PriceVelocityDetector(PriceVelocityConfig())
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    for i, price in enumerate([0.02, 0.98, 0.02, 0.99]):
        detector.ingest("m", _fv(), _snap(price), now + timedelta(seconds=i * 30))


@pytest.mark.unit
def test_price_velocity_state_round_trip_preserves_behavior() -> None:
    detector = PriceVelocityDetector(PriceVelocityConfig())
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    for i in range(30):
        detector.ingest("m", _fv(), _snap(0.5), now + timedelta(seconds=i * 30))
    state = detector.state_dict("m")
    restored = PriceVelocityDetector(PriceVelocityConfig())
    restored.load_state("m", state)
    assert restored.state_dict("m") == state


@pytest.mark.unit
def test_price_velocity_reset_clears_state() -> None:
    detector = PriceVelocityDetector(PriceVelocityConfig())
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    detector.ingest("m", _fv(), _snap(0.5), now)
    detector.reset("m")
    assert detector.state_dict("m") == {
        "bocpd": None,
        "last_price": None,
        "cooldown_until": None,
        "observations": 0,
        "running_mean": None,
    }
