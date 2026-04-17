"""Empirical false-positive rate computation per (detector, market).

Phase 1 ships the contract and a synthetic-label path. Real empirical
FPR depends on the labeled newsworthy-event corpus produced by the
downstream labeling workstream; once that is populated, FPRRecord rows
land in the calibration_fpr DuckDB table and are consumed by the
threshold tuner.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class NewsworthyEventLike(Protocol):
    """Minimal surface required from labels for the FPR computation."""

    market_id: str
    occurred_at: datetime


class FPRRecord(BaseModel):
    """Empirical FPR for one (detector, market) slice."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detector_id: str
    market_id: str
    fpr: float
    sample_size: int
    computed_at: datetime
    label_protocol_version: str


def compute_empirical_fpr(
    detector_id: str,
    market_id: str,
    detected_at_values: Sequence[datetime],
    event_occurred_at_values: Sequence[datetime],
    now: datetime,
    lead_window: timedelta = timedelta(hours=24),
    label_protocol_version: str = "v0",
) -> FPRRecord:
    """FP / (FP + TN) per docs/methodology/labeling-protocol.md §True Positive.

    A detector firing at `t_signal` is a true positive if some labeled
    event for the same market occurred in `[t_signal, t_signal + lead_window]`.
    All other firings are false positives; every observation window
    without a label in range contributes to the TN denominator. `now`
    is a required parameter so every FPRRecord's computed_at is
    deterministic across backtest replays — matching the pipeline-wide
    "now as a parameter" invariant.
    """
    total_signals = len(detected_at_values)
    if total_signals == 0:
        return FPRRecord(
            detector_id=detector_id,
            market_id=market_id,
            fpr=0.0,
            sample_size=0,
            computed_at=now,
            label_protocol_version=label_protocol_version,
        )
    true_positives = 0
    for t_signal in detected_at_values:
        window_end = t_signal + lead_window
        for event_t in event_occurred_at_values:
            if t_signal <= event_t <= window_end:
                true_positives += 1
                break
    false_positives = total_signals - true_positives
    sample_size = total_signals
    fpr = false_positives / max(sample_size, 1)
    return FPRRecord(
        detector_id=detector_id,
        market_id=market_id,
        fpr=fpr,
        sample_size=sample_size,
        computed_at=now,
        label_protocol_version=label_protocol_version,
    )
