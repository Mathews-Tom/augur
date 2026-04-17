"""Deterministic severity derivation.

Severity is `magnitude * confidence` scored against per-tier
thresholds. The formula is pure code (not configuration) so every
consumer can reproduce the mapping locally without a network round
trip. Changing the thresholds requires a schema-version bump on the
IntelligenceBrief contract since downstream routing depends on stable
severity output.

Threshold table
---------------

================  ======  =======  ======
liquidity_tier    high    medium   low
================  ======  =======  ======
high              > 0.6   > 0.3    ≤ 0.3
mid               > 0.7   ≤ 0.7    ≤ 0.7
low               —       —        always
================  ======  =======  ======
"""

from __future__ import annotations

from typing import Literal

from augur_signals.models import MarketSignal

Severity = Literal["high", "medium", "low"]


def derive_severity(signal: MarketSignal) -> Severity:
    """Return the deterministic severity label for *signal*.

    The score is `magnitude * confidence` (both in [0, 1]); the
    threshold applied depends on the liquidity tier. Low-tier markets
    always emit "low" severity — the sample size on low-tier reliability
    curves is too thin to justify higher confidence in a human channel.
    """
    score = signal.magnitude * signal.confidence
    if signal.liquidity_tier == "high":
        if score > 0.6:
            return "high"
        if score > 0.3:
            return "medium"
        return "low"
    if signal.liquidity_tier == "mid":
        if score > 0.7:
            return "medium"
        return "low"
    return "low"
