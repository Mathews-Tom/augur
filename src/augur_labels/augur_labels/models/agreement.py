"""AgreementReport — inter-annotator agreement metrics.

Produced by the workflow enforcer before candidate promotion and by
the agreement CLI command for retrospective analysis. The ``targets``
in docs/methodology/labeling-protocol.md §Inter-Annotator Agreement
are the thresholds that ``meets_targets`` checks.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgreementReport(BaseModel):
    """Summary of one pair of annotators' agreement over a window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    annotator_pair: tuple[str, str]
    window_start: datetime
    window_end: datetime
    candidate_count: int
    event_existence_kappa: float
    timestamp_agreement_60s: float
    market_association_jaccard_mean: float
    category_assignment_kappa: float
    meets_targets: bool
