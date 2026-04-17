"""Volume-spike detector — EWMA z-score with configurable threshold.

Each market maintains its own EWMA mean and variance of volume_ratio_1h
so the z-score reflects recent-history volatility rather than a global
baseline. The raw z-score is exposed as the signal magnitude; the FDR
controller is composed downstream at the engine level once the
calibration layer lands, so this detector deliberately does not gate
on it internally.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from augur_signals.calibration.liquidity_tier import banding
from augur_signals.detectors._config import VolumeSpikeConfig
from augur_signals.models import (
    FeatureVector,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)


class VolumeSpikeDetector:
    """Detector firing on sustained upward deviations from the EWMA baseline."""

    detector_id: str = "volume_spike_ewma_z_v1"
    signal_type: SignalType = SignalType.VOLUME_SPIKE
    _WARMUP_OBSERVATIONS: int = 30

    def __init__(
        self,
        config: VolumeSpikeConfig,
        calibration_provenance: str = "volume_spike_ewma_z_v1@identity_v0",
    ) -> None:
        self._config = config
        self._provenance = calibration_provenance
        self._ewma_mean: dict[str, float] = {}
        self._ewma_var: dict[str, float] = {}
        self._observations: dict[str, int] = {}

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
        if snapshot.volume_24h < self._config.min_absolute_volume:
            return None
        ratio = feature.volume_ratio_1h
        mean = self._ewma_mean.setdefault(market_id, 1.0)
        var = self._ewma_var.setdefault(market_id, 0.25)
        alpha = self._config.ewma_alpha
        diff = ratio - mean
        updated_mean = mean + alpha * diff
        updated_var = (1 - alpha) * (var + alpha * diff * diff)
        self._ewma_mean[market_id] = updated_mean
        self._ewma_var[market_id] = updated_var
        observations = self._observations.get(market_id, 0) + 1
        self._observations[market_id] = observations
        if observations < self._WARMUP_OBSERVATIONS:
            return None
        std = max(1e-6, updated_var**0.5)
        z = (ratio - updated_mean) / std
        if z < self._config.minimum_z:
            return None
        magnitude = min(1.0, max(0.0, (z - self._config.minimum_z) / 6.0))
        tier = banding(snapshot.volume_24h)
        return MarketSignal(
            signal_id=new_signal_id(),
            market_id=market_id,
            platform=snapshot.platform,
            signal_type=self.signal_type,
            magnitude=magnitude,
            direction=1,
            confidence=magnitude,
            fdr_adjusted=False,
            detected_at=now,
            window_seconds=3600,
            liquidity_tier=tier,
            raw_features={
                "volume_ratio_1h": ratio,
                "ewma_mean": updated_mean,
                "ewma_std": std,
                "z_score": z,
                "calibration_provenance": self._provenance,
            },
        )

    def state_dict(self, market_id: str) -> dict[str, Any]:
        return {
            "ewma_mean": self._ewma_mean.get(market_id),
            "ewma_var": self._ewma_var.get(market_id),
            "observations": self._observations.get(market_id, 0),
        }

    def load_state(self, market_id: str, state: dict[str, Any]) -> None:
        if state.get("ewma_mean") is not None:
            self._ewma_mean[market_id] = float(state["ewma_mean"])
        if state.get("ewma_var") is not None:
            self._ewma_var[market_id] = float(state["ewma_var"])
        self._observations[market_id] = int(state.get("observations", 0))

    def reset(self, market_id: str) -> None:
        self._ewma_mean.pop(market_id, None)
        self._ewma_var.pop(market_id, None)
        self._observations.pop(market_id, None)
