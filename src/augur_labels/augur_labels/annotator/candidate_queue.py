"""In-memory candidate queue used by the annotator CLI.

Real deployments back the queue with the parquet corpus; this module
exposes the shape so tests and the workflow enforcer can operate on
any concrete queue backend.
"""

from __future__ import annotations

from collections.abc import Iterable

from augur_labels.models import EventCandidate, LabelDecision


class CandidateQueue:
    """In-memory candidate store indexed by ``candidate_id``."""

    def __init__(self) -> None:
        self._candidates: dict[str, EventCandidate] = {}
        self._decisions: dict[str, list[LabelDecision]] = {}

    def enqueue(self, candidates: Iterable[EventCandidate]) -> None:
        for candidate in candidates:
            if candidate.candidate_id in self._candidates:
                continue
            self._candidates[candidate.candidate_id] = candidate
            self._decisions.setdefault(candidate.candidate_id, [])

    def record(self, decision: LabelDecision) -> None:
        if decision.candidate_id not in self._candidates:
            raise KeyError(f"unknown candidate_id={decision.candidate_id!r}")
        for existing in self._decisions[decision.candidate_id]:
            if existing.annotator_id == decision.annotator_id:
                raise ValueError(
                    f"annotator {decision.annotator_id!r} has already decided "
                    f"on candidate {decision.candidate_id!r}"
                )
        self._decisions[decision.candidate_id].append(decision)

    def decisions_for(self, candidate_id: str) -> list[LabelDecision]:
        return list(self._decisions.get(candidate_id, []))

    def get(self, candidate_id: str) -> EventCandidate:
        return self._candidates[candidate_id]

    def pending(self) -> list[EventCandidate]:
        return [c for cid, c in self._candidates.items() if len(self._decisions.get(cid, [])) < 2]

    def __contains__(self, candidate_id: object) -> bool:
        return candidate_id in self._candidates
