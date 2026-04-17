"""Per-market liquidity tier banding.

The instantaneous per-snapshot estimator is used at signal emission
time; the canonical daily tier reconciliation against a 7-day rolling
volume window runs as part of the calibration nightly job per
docs/foundations/glossary.md §Liquidity Tier.
"""

from __future__ import annotations

from typing import Literal

LiquidityTier = Literal["high", "mid", "low"]


def banding(volume_24h: float) -> LiquidityTier:
    """Return the per-snapshot liquidity tier for a 24h dollar volume."""
    if volume_24h >= 250_000:
        return "high"
    if volume_24h >= 50_000:
        return "mid"
    return "low"
