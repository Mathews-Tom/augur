"""Cross-market divergence detector.

Operates on batches across the full polling cycle so the FDR
controller sees all candidate market pairs simultaneously. For each
related-market pair with a configured historical correlation at or
above the threshold, the detector computes the current Spearman rank
correlation, applies the Fisher-z transform, and compares the z to the
prior z. Pairs whose divergence p-value survives BH-FDR at the target
`q` produce signals per docs/methodology/calibration-methodology.md
§Cross-Market Divergence.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from augur_signals.calibration.fdr_controller import FDRController
from augur_signals.calibration.liquidity_tier import banding
from augur_signals.detectors._config import CrossMarketConfig
from augur_signals.models import (
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)


@dataclass(frozen=True, slots=True)
class RelatedMarketPair:
    """A taxonomy edge eligible for divergence evaluation."""

    market_a: str
    market_b: str
    historical_z: float


@dataclass(slots=True)
class _PairState:
    """Rolling price series for a related-market pair."""

    prices_a: list[float] = field(default_factory=list)
    prices_b: list[float] = field(default_factory=list)


def _ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda p: p[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman_correlation(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 3 or len(a) != len(b):
        return 0.0
    ra = _ranks(a)
    rb = _ranks(b)
    n = len(ra)
    mean_a = sum(ra) / n
    mean_b = sum(rb) / n
    numerator = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(n))
    var_a = sum((r - mean_a) ** 2 for r in ra)
    var_b = sum((r - mean_b) ** 2 for r in rb)
    denom = math.sqrt(var_a * var_b)
    if denom <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denom))


def _fisher_z(rho: float) -> float:
    clipped = max(-0.999999, min(0.999999, rho))
    return 0.5 * math.log((1.0 + clipped) / (1.0 - clipped))


def _two_sided_normal_p(value: float) -> float:
    """Upper-tail two-sided normal p-value using the error function."""
    return math.erfc(abs(value) / math.sqrt(2.0))


class CrossMarketDivergenceDetector:
    """Batch detector over curated related-market pairs."""

    detector_id: str = "cross_market_fisher_bh_v1"
    signal_type: SignalType = SignalType.CROSS_MARKET_DIVERGENCE
    _MIN_OBSERVATIONS: int = 10

    def __init__(
        self,
        config: CrossMarketConfig,
        fdr_controller: FDRController,
        related_pairs: Sequence[RelatedMarketPair],
        calibration_provenance: str = "cross_market_fisher_bh_v1@identity_v0",
    ) -> None:
        self._config = config
        self._fdr = fdr_controller
        self._pairs = list(related_pairs)
        self._state: dict[tuple[str, str], _PairState] = {
            (p.market_a, p.market_b): _PairState() for p in related_pairs
        }
        self._provenance = calibration_provenance

    def evaluate_batch(
        self,
        snapshots: dict[str, MarketSnapshot],
        now: datetime,
    ) -> list[MarketSignal]:
        candidates: list[
            tuple[str, str, float, float, MarketSnapshot, MarketSnapshot, RelatedMarketPair]
        ] = []
        for pair in self._pairs:
            snap_a = snapshots.get(pair.market_a)
            snap_b = snapshots.get(pair.market_b)
            if snap_a is None or snap_b is None:
                continue
            if snap_a.closes_at is not None:
                remaining = (snap_a.closes_at - now).total_seconds()
                if 0.0 <= remaining < self._config.resolution_exclusion_seconds:
                    continue
            state = self._state[(pair.market_a, pair.market_b)]
            state.prices_a.append(snap_a.last_price)
            state.prices_b.append(snap_b.last_price)
            max_points = max(self._MIN_OBSERVATIONS, self._config.window_seconds // 60)
            if len(state.prices_a) > max_points:
                state.prices_a.pop(0)
                state.prices_b.pop(0)
            if len(state.prices_a) < self._MIN_OBSERVATIONS:
                continue
            rho = _spearman_correlation(state.prices_a, state.prices_b)
            current_z = _fisher_z(rho)
            z_delta = current_z - pair.historical_z
            std_err = 1.0 / math.sqrt(max(1.0, len(state.prices_a) - 3))
            test_statistic = z_delta / std_err
            p_value = _two_sided_normal_p(test_statistic)
            # Pair-level key so the FDR controller's set return distinguishes
            # between pairs that share a market_a.
            pair_key = f"{pair.market_a}::{pair.market_b}"
            candidates.append((pair_key, pair.market_a, rho, p_value, snap_a, snap_b, pair))

        if not candidates:
            return []
        passing = self._fdr.submit_pvalues(
            self.detector_id, [(candidate[0], candidate[3]) for candidate in candidates]
        )
        signals: list[MarketSignal] = []
        for pair_key, market_a, rho, p_value, snap_a, snap_b, pair in candidates:
            if pair_key not in passing:
                continue
            magnitude = min(1.0, max(0.0, 1.0 - p_value))
            tier = banding(snap_a.volume_24h)
            signals.append(
                MarketSignal(
                    signal_id=new_signal_id(),
                    market_id=market_a,
                    platform=snap_a.platform,
                    signal_type=self.signal_type,
                    magnitude=magnitude,
                    direction=0,
                    confidence=magnitude,
                    fdr_adjusted=True,
                    detected_at=now,
                    window_seconds=self._config.window_seconds,
                    liquidity_tier=tier,
                    related_market_ids=[pair.market_b],
                    raw_features={
                        "spearman_rho": rho,
                        "p_value": p_value,
                        "historical_z": pair.historical_z,
                        "related_market_id": snap_b.market_id,
                        "calibration_provenance": self._provenance,
                    },
                )
            )
        return signals
