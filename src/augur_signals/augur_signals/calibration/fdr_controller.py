"""Benjamini-Hochberg FDR controller shared across detectors.

Detectors that batch p-values per polling cycle submit
``(signal_id, p_value)`` pairs via :meth:`submit_pvalues`; the
controller applies BH correction at the configured target ``q`` and
returns the set of signal IDs that pass. See
docs/methodology/calibration-methodology.md §BH-FDR for the rationale.
"""

from __future__ import annotations

from collections.abc import Sequence

from augur_signals.calibration._config import CalibrationConfig


def benjamini_hochberg(p_values: Sequence[float], q: float) -> list[bool]:
    """Return a boolean mask marking each hypothesis accepted at FDR ``q``.

    Implements the Benjamini-Hochberg step-up procedure: sort p-values
    ascending, find the largest rank ``k`` such that ``p_(k) ≤ (k/m) q``,
    accept all hypotheses whose p-value is at most ``p_(k)``.
    """
    m = len(p_values)
    if m == 0:
        return []
    if not 0.0 < q < 1.0:
        raise ValueError("target FDR q must lie in (0, 1)")
    ranked = sorted(enumerate(p_values), key=lambda pair: pair[1])
    largest_k = -1
    for rank, (_, p) in enumerate(ranked, start=1):
        if p <= (rank / m) * q:
            largest_k = rank
    accepted = [False] * m
    if largest_k < 0:
        return accepted
    for rank, (orig_idx, _) in enumerate(ranked, start=1):
        if rank <= largest_k:
            accepted[orig_idx] = True
    return accepted


class FDRController:
    """Per-detector batch FDR controller."""

    def __init__(self, config: CalibrationConfig) -> None:
        self._q = config.target_fdr_q

    def submit_pvalues(self, detector_id: str, batch: Sequence[tuple[str, float]]) -> set[str]:
        """Return the set of signal IDs accepted by the BH procedure."""
        del detector_id  # per-detector tuning deferred until empirical FPR is populated.
        if not batch:
            return set()
        p_values = [p for _, p in batch]
        accepted = benjamini_hochberg(p_values, self._q)
        return {signal_id for (signal_id, _), keep in zip(batch, accepted, strict=True) if keep}
