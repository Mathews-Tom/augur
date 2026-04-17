"""Regime-shift detector — two-sided CUSUM on volatility.

Fires only after a minimum dormancy period, so a sustained increase in
volatility following a quiet window is what trips the detector.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from augur_signals.calibration.liquidity_tier import banding
from augur_signals.detectors._config import RegimeShiftConfig
from augur_signals.detectors._cusum import TwoSidedCUSUM
from augur_signals.models import (
    FeatureVector,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)


class RegimeShiftDetector:
    """CUSUM-based regime-shift detector with dormancy gate."""

    detector_id: str = "regime_shift_cusum_v1"
    signal_type: SignalType = SignalType.REGIME_SHIFT
    _WARMUP_OBSERVATIONS: int = 30

    def __init__(
        self,
        config: RegimeShiftConfig,
        calibration_provenance: str = "regime_shift_cusum_v1@identity_v0",
    ) -> None:
        self._config = config
        self._provenance = calibration_provenance
        self._cusum: dict[str, TwoSidedCUSUM] = {}
        self._observations: dict[str, int] = {}
        self._last_signal_at: dict[str, datetime] = {}
        self._dormant_since: dict[str, datetime] = {}

    def warmup_required(self) -> int:
        return self._WARMUP_OBSERVATIONS

    def ingest(
        self,
        market_id: str,
        feature: FeatureVector,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> MarketSignal | None:
        if snapshot.closes_at is not None:
            remaining = (snapshot.closes_at - now).total_seconds()
            if 0.0 <= remaining < self._config.resolution_exclusion_seconds:
                return None

        cusum = self._cusum.setdefault(
            market_id,
            TwoSidedCUSUM(
                k_sigma=self._config.k_multiplier,
                h_sigma=self._config.h_multiplier,
            ),
        )
        observations = self._observations.get(market_id, 0) + 1
        self._observations[market_id] = observations
        self._dormant_since.setdefault(market_id, now)

        positive, negative = cusum.update(feature.volatility_1h)
        threshold = cusum.threshold()

        if observations < self._WARMUP_OBSERVATIONS:
            return None
        dormancy = (now - self._dormant_since[market_id]).total_seconds()
        if dormancy < self._config.dormancy_minimum_seconds:
            if abs(positive) <= threshold and abs(negative) <= threshold:
                return None
            # Reset dormancy window when a breach happens before the minimum.
            self._dormant_since[market_id] = now
            return None

        if positive <= threshold and abs(negative) <= threshold:
            return None
        direction: Literal[-1, 0, 1] = 1 if positive > threshold else -1
        magnitude = min(1.0, max(abs(positive), abs(negative)) / (threshold * 2.0 + 1e-9))
        tier = banding(snapshot.volume_24h)
        cusum.reset()
        self._last_signal_at[market_id] = now
        cooldown = timedelta(
            seconds=int(
                self._config.dormancy_minimum_seconds * self._config.adaptive_cooldown_factor
            )
        )
        self._dormant_since[market_id] = now + cooldown

        return MarketSignal(
            signal_id=new_signal_id(),
            market_id=market_id,
            platform=snapshot.platform,
            signal_type=self.signal_type,
            magnitude=magnitude,
            direction=direction,
            confidence=magnitude,
            fdr_adjusted=False,
            detected_at=now,
            window_seconds=3600,
            liquidity_tier=tier,
            raw_features={
                "positive_cusum": positive,
                "negative_cusum": negative,
                "threshold": threshold,
                "calibration_provenance": self._provenance,
            },
        )

    def state_dict(self, market_id: str) -> dict[str, Any]:
        cusum = self._cusum.get(market_id)
        return {
            "cusum": {
                "positive": cusum.positive,
                "negative": cusum.negative,
                "sigma_estimate": cusum.sigma_estimate,
                "mean_estimate": cusum.mean_estimate,
                "samples": cusum.samples,
            }
            if cusum
            else None,
            "observations": self._observations.get(market_id, 0),
            "dormant_since": (
                self._dormant_since[market_id].isoformat()
                if market_id in self._dormant_since
                else None
            ),
        }

    def load_state(self, market_id: str, state: dict[str, Any]) -> None:
        cusum_state = state.get("cusum")
        if cusum_state:
            cusum = TwoSidedCUSUM(
                k_sigma=self._config.k_multiplier,
                h_sigma=self._config.h_multiplier,
            )
            cusum.positive = float(cusum_state["positive"])
            cusum.negative = float(cusum_state["negative"])
            cusum.sigma_estimate = float(cusum_state["sigma_estimate"])
            cusum.mean_estimate = float(cusum_state["mean_estimate"])
            cusum.samples = int(cusum_state["samples"])
            self._cusum[market_id] = cusum
        self._observations[market_id] = int(state.get("observations", 0))
        dormant = state.get("dormant_since")
        if dormant is not None:
            self._dormant_since[market_id] = datetime.fromisoformat(str(dormant))

    def reset(self, market_id: str) -> None:
        self._cusum.pop(market_id, None)
        self._observations.pop(market_id, None)
        self._last_signal_at.pop(market_id, None)
        self._dormant_since.pop(market_id, None)
