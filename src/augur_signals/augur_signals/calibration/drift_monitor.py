"""Drift monitor for detector scoring distributions.

Computes Population Stability Index (PSI) and a Kolmogorov-Smirnov
statistic over baseline vs current score populations. When either
metric exceeds its configured threshold, the monitor flags a
`CalibrationStaleEvent` for operations review so the detector
thresholds can be retuned.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from augur_signals.calibration._config import CalibrationConfig


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Outcome of one drift check."""

    detector_id: str
    psi: float
    ks_statistic: float
    ks_p_value: float
    triggered: bool
    triggered_metrics: list[Literal["psi", "ks"]] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime(2026, 1, 1).astimezone())


def _population_stability_index(
    baseline: Sequence[float],
    current: Sequence[float],
    bins: int = 10,
) -> float:
    if not baseline or not current:
        return 0.0
    lo = min(min(baseline), min(current))
    hi = max(max(baseline), max(current))
    if hi == lo:
        return 0.0

    def fractions(values: Sequence[float]) -> list[float]:
        counts = [0] * bins
        for v in values:
            idx = min(bins - 1, max(0, int((v - lo) / (hi - lo) * bins)))
            counts[idx] += 1
        total = len(values)
        return [c / total for c in counts]

    base_fracs = fractions(baseline)
    cur_fracs = fractions(current)
    psi = 0.0
    for b, c in zip(base_fracs, cur_fracs, strict=True):
        if b == 0 and c == 0:
            continue
        b_safe = max(b, 1e-6)
        c_safe = max(c, 1e-6)
        psi += (c_safe - b_safe) * math.log(c_safe / b_safe)
    return psi


def _ks_statistic(baseline: Sequence[float], current: Sequence[float]) -> tuple[float, float]:
    if not baseline or not current:
        return 0.0, 1.0
    combined = sorted(set(baseline) | set(current))
    n1, n2 = len(baseline), len(current)
    max_diff = 0.0
    sorted_b = sorted(baseline)
    sorted_c = sorted(current)

    def _cdf(values: list[float], threshold: float) -> float:
        count = 0
        for v in values:
            if v <= threshold:
                count += 1
            else:
                break
        return count / len(values)

    for threshold in combined:
        cdf_b = _cdf(sorted_b, threshold)
        cdf_c = _cdf(sorted_c, threshold)
        max_diff = max(max_diff, abs(cdf_b - cdf_c))
    # Two-sample KS asymptotic p-value approximation.
    scaling = math.sqrt(n1 * n2 / (n1 + n2))
    stat = scaling * max_diff
    p_value = 2.0 * math.exp(-2.0 * stat * stat) if stat > 0 else 1.0
    return max_diff, min(1.0, max(0.0, p_value))


class DriftMonitor:
    """Detects calibration drift by comparing baseline to current scores."""

    def __init__(self, config: CalibrationConfig) -> None:
        self._config = config

    def check(
        self,
        detector_id: str,
        baseline_scores: Sequence[float],
        current_scores: Sequence[float],
        checked_at: datetime,
    ) -> DriftReport:
        psi = _population_stability_index(baseline_scores, current_scores)
        ks_stat, ks_p = _ks_statistic(baseline_scores, current_scores)
        triggered_metrics: list[Literal["psi", "ks"]] = []
        if psi > self._config.psi_trigger_threshold:
            triggered_metrics.append("psi")
        if ks_p < self._config.ks_p_value_threshold:
            triggered_metrics.append("ks")
        return DriftReport(
            detector_id=detector_id,
            psi=psi,
            ks_statistic=ks_stat,
            ks_p_value=ks_p,
            triggered=bool(triggered_metrics),
            triggered_metrics=triggered_metrics,
            checked_at=checked_at,
        )
