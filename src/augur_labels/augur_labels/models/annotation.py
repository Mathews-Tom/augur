"""Annotator identity and per-decision models.

Each `LabelDecision` represents one annotator's call on one candidate.
The workflow enforcer consumes pairs of decisions on the same
candidate_id to decide whether to promote.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnnotatorIdentity(BaseModel):
    """Opaque annotator identifier plus optional display name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    annotator_id: str
    display_name: str | None = None


class LabelDecision(BaseModel):
    """One annotator's call on one candidate.

    Fields marked `required if qualifies` are enforced by a
    model_validator on promotion rather than at construction so an
    annotator can record "does not qualify" decisions without supplying
    event metadata.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    candidate_id: str
    annotator_id: str
    decided_at: datetime
    qualifies: bool
    timestamp: datetime | None = None
    market_ids: list[str] = Field(default_factory=list)
    category: str | None = None
    notes: str | None = None
