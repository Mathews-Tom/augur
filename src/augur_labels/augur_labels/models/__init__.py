"""Data contracts for the labeling pipeline.

Exports the Pydantic models every other augur_labels module relies on.
Schema semantics are authoritative in
docs/methodology/labeling-protocol.md.
"""

from __future__ import annotations

from augur_labels.models.agreement import AgreementReport
from augur_labels.models.annotation import AnnotatorIdentity, LabelDecision
from augur_labels.models.event import EventCandidate, NewsworthyEvent
from augur_labels.models.source import QualifyingSource, SourcePublication

__all__ = [
    "AgreementReport",
    "AnnotatorIdentity",
    "EventCandidate",
    "LabelDecision",
    "NewsworthyEvent",
    "QualifyingSource",
    "SourcePublication",
]
