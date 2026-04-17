"""Reliability curves per (detector, liquidity_tier).

Phase 1 ships with an identity-curve placeholder: `calibrate(score) =
score` with `curve_version = "identity_v0"`. This satisfies the
MarketSignal calibration_provenance invariant during the warmup period
before real curves can be built from a labeled corpus. Subsequent
workstreams consume labels to fit empirical curves, which are then
loaded via :meth:`ReliabilityAnalyzer.register_curve` and take
precedence over the identity placeholder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

LiquidityTier = Literal["high", "mid", "low"]


class ReliabilityCurve(BaseModel):
    """Monotone-nondecreasing mapping from raw score to empirical precision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detector_id: str
    liquidity_tier: LiquidityTier
    curve_version: str
    deciles: list[tuple[float, float]]
    built_at: datetime


class ReliabilityAnalyzer:
    """Serves calibrated confidence scores from cached curves."""

    IDENTITY_VERSION: str = "identity_v0"

    def __init__(self) -> None:
        self._curves: dict[tuple[str, LiquidityTier], ReliabilityCurve] = {}

    def register_curve(self, curve: ReliabilityCurve) -> None:
        self._curves[(curve.detector_id, curve.liquidity_tier)] = curve

    def curve_version(self, detector_id: str, liquidity_tier: LiquidityTier) -> str:
        curve = self._curves.get((detector_id, liquidity_tier))
        return curve.curve_version if curve else self.IDENTITY_VERSION

    def calibrate(
        self,
        detector_id: str,
        liquidity_tier: LiquidityTier,
        raw_score: float,
    ) -> float:
        """Linearly interpolate the raw score onto the cached curve."""
        curve = self._curves.get((detector_id, liquidity_tier))
        if curve is None or not curve.deciles:
            return max(0.0, min(1.0, raw_score))
        for (x0, y0), (x1, y1) in zip(curve.deciles, curve.deciles[1:], strict=False):
            if x0 <= raw_score <= x1:
                if x1 == x0:
                    return y0
                ratio = (raw_score - x0) / (x1 - x0)
                return y0 + ratio * (y1 - y0)
        # Outside the decile range — clamp to the nearest endpoint.
        if raw_score < curve.deciles[0][0]:
            return curve.deciles[0][1]
        return curve.deciles[-1][1]


def build_identity_curve(detector_id: str, liquidity_tier: LiquidityTier) -> ReliabilityCurve:
    """Return the identity placeholder curve for *detector_id*."""
    return ReliabilityCurve(
        detector_id=detector_id,
        liquidity_tier=liquidity_tier,
        curve_version=ReliabilityAnalyzer.IDENTITY_VERSION,
        deciles=[(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)],
        built_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
