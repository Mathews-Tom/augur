"""Price velocity detector — Beta-Binomial BOCPD with per-market state.

Implements the method in docs/methodology/calibration-methodology.md
§Price Velocity for change-point detection on a bounded-probability
price series. Every detector instance carries a per-market
BetaBinomialBOCPD and a cooldown timer so the same underlying change
does not fire repeatedly.

The pre-resolution exclusion (6 h before market close) is enforced
inside `ingest` so a signal in the window is never returned,
regardless of the posterior probability.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from augur_signals.calibration.liquidity_tier import banding
from augur_signals.detectors._bocpd import BetaBinomialBOCPD
from augur_signals.detectors._config import PriceVelocityConfig
from augur_signals.models import (
    FeatureVector,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)


class PriceVelocityDetector:
    """Detector wrapping the BOCPD math with cooldown and resolution gates."""

    detector_id: str = "price_velocity_bocpd_beta_v1"
    signal_type: SignalType = SignalType.PRICE_VELOCITY

    _WARMUP_OBSERVATIONS: int = 50

    def __init__(
        self,
        config: PriceVelocityConfig,
        calibration_provenance: str = "price_velocity_bocpd_beta_v1@identity_v0",
    ) -> None:
        self._config = config
        self._provenance = calibration_provenance
        self._bocpd: dict[str, BetaBinomialBOCPD] = {}
        self._last_price: dict[str, float] = {}
        self._cooldown_until: dict[str, datetime] = {}
        self._observations: dict[str, int] = {}
        self._running_mean: dict[str, float] = {}

    def warmup_required(self) -> int:
        return self._WARMUP_OBSERVATIONS

    def ingest(
        self,
        market_id: str,
        feature: FeatureVector,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> MarketSignal | None:
        del feature  # price series drives the detector directly.
        # Pre-resolution exclusion.
        if snapshot.closes_at is not None:
            remaining = (snapshot.closes_at - now).total_seconds()
            if 0.0 <= remaining < self._config.resolution_exclusion_seconds:
                return None
        # Cooldown.
        cooldown = self._cooldown_until.get(market_id)
        if cooldown is not None and now < cooldown:
            return None

        bocpd = self._bocpd.setdefault(
            market_id,
            BetaBinomialBOCPD(
                hazard_rate=self._config.hazard_rate,
                alpha_prior=self._config.alpha_prior,
                beta_prior=self._config.beta_prior,
                run_length_cap=self._config.run_length_cap,
            ),
        )
        # Bernoulli-projected observation against the running mean gives
        # the posterior the sharpness required for the fire threshold.
        # The running mean updates with alpha=0.05 so a sustained level
        # shift dominates an isolated tick.
        mean = self._running_mean.get(market_id, snapshot.last_price)
        updated_mean = 0.95 * mean + 0.05 * snapshot.last_price
        self._running_mean[market_id] = updated_mean
        bernoulli_obs = 1.0 if snapshot.last_price > mean else 0.0
        p_change, expected_rl = bocpd.update(bernoulli_obs)
        prior_price = self._last_price.get(market_id)
        self._last_price[market_id] = snapshot.last_price
        self._observations[market_id] = self._observations.get(market_id, 0) + 1

        # Suppress firing until the run-length distribution has settled
        # below the fire threshold on steady-state input.
        if self._observations[market_id] < self._WARMUP_OBSERVATIONS:
            return None
        if p_change < self._config.fire_threshold:
            return None

        direction_sign: Literal[-1, 0, 1] = 0
        if prior_price is not None:
            if snapshot.last_price > prior_price:
                direction_sign = 1
            elif snapshot.last_price < prior_price:
                direction_sign = -1
        tier = banding(snapshot.volume_24h)
        self._cooldown_until[market_id] = now + timedelta(seconds=self._config.cooldown_seconds)

        return MarketSignal(
            signal_id=new_signal_id(),
            market_id=market_id,
            platform=snapshot.platform,
            signal_type=self.signal_type,
            magnitude=max(0.0, min(1.0, p_change)),
            direction=direction_sign,
            confidence=max(0.0, min(1.0, p_change)),
            fdr_adjusted=False,
            detected_at=now,
            window_seconds=300,
            liquidity_tier=tier,
            raw_features={
                "posterior_p_change": p_change,
                "expected_run_length": expected_rl,
                "calibration_provenance": self._provenance,
            },
        )

    def state_dict(self, market_id: str) -> dict[str, Any]:
        bocpd = self._bocpd.get(market_id)
        return {
            "bocpd": bocpd.state_dict() if bocpd else None,
            "last_price": self._last_price.get(market_id),
            "cooldown_until": (
                cooldown.isoformat() if (cooldown := self._cooldown_until.get(market_id)) else None
            ),
            "observations": self._observations.get(market_id, 0),
            "running_mean": self._running_mean.get(market_id),
        }

    def load_state(self, market_id: str, state: dict[str, Any]) -> None:
        bocpd_state = state.get("bocpd")
        if bocpd_state:
            bocpd = BetaBinomialBOCPD(
                hazard_rate=self._config.hazard_rate,
                alpha_prior=self._config.alpha_prior,
                beta_prior=self._config.beta_prior,
                run_length_cap=self._config.run_length_cap,
            )
            bocpd.load_state(bocpd_state)
            self._bocpd[market_id] = bocpd
        last_price = state.get("last_price")
        if last_price is not None:
            self._last_price[market_id] = float(last_price)
        cooldown = state.get("cooldown_until")
        if cooldown is not None:
            self._cooldown_until[market_id] = datetime.fromisoformat(str(cooldown))
        observations = state.get("observations", 0)
        self._observations[market_id] = int(observations)
        running_mean = state.get("running_mean")
        if running_mean is not None:
            self._running_mean[market_id] = float(running_mean)

    def reset(self, market_id: str) -> None:
        self._bocpd.pop(market_id, None)
        self._last_price.pop(market_id, None)
        self._cooldown_until.pop(market_id, None)
        self._observations.pop(market_id, None)
        self._running_mean.pop(market_id, None)
