"""Event-candidate and NewsworthyEvent models.

NewsworthyEvent is the binding contract consumed by the calibration
layer via the signal-to-event join. EventCandidate is the intermediate
state: a candidate is promoted to a NewsworthyEvent only after two
annotators agree per the workflow enforcer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from augur_labels.models.source import SourceId, SourcePublication


class EventCandidate(BaseModel):
    """A candidate awaiting annotator decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    discovered_at: datetime
    publications: list[SourcePublication]
    suggested_market_ids: list[str] = Field(default_factory=list)


class NewsworthyEvent(BaseModel):
    """A labeled event that survived the two-annotator workflow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    ground_truth_timestamp: datetime
    market_ids: list[str]
    category: str
    headline: str
    source_urls: list[str]
    source_publishers: list[SourceId]
    labeler_ids: list[str]
    label_protocol_version: str
    corrects: str | None = None
    status: Literal["labeled", "candidate", "superseded", "rejected"]
    created_at: datetime
