"""Two-annotator workflow enforcer.

Per docs/methodology/labeling-protocol.md §Annotator Protocol,
promotion requires at least two distinct annotators, agreement on
event existence, timestamp proximity, and sufficient market-
association overlap. The enforcer is a pure function over the
candidate's decisions; the CLI surfaces the decisions it collects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from augur_labels._config import WorkflowConfig
from augur_labels.annotator.candidate_queue import CandidateQueue
from augur_labels.models import LabelDecision


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Outcome of WorkflowEnforcer.can_promote."""

    allowed: bool
    reason: str


class WorkflowEnforcer:
    """Decides whether a candidate may be promoted to a NewsworthyEvent."""

    def __init__(self, config: WorkflowConfig, queue: CandidateQueue) -> None:
        self._config = config
        self._queue = queue

    def can_promote(self, candidate_id: str) -> PromotionDecision:
        if candidate_id not in self._queue:
            return PromotionDecision(False, "unknown candidate")
        decisions = self._queue.decisions_for(candidate_id)
        if len({d.annotator_id for d in decisions}) < 2:
            return PromotionDecision(False, "needs two distinct annotators")
        qualifying = [d for d in decisions if d.qualifies]
        if len(qualifying) < 2:
            return PromotionDecision(False, "annotators disagree on event existence")
        timestamp_failure = self._timestamp_failure(qualifying)
        if timestamp_failure is not None:
            return timestamp_failure
        market_failure = self._market_failure(qualifying)
        if market_failure is not None:
            return market_failure
        return PromotionDecision(True, "eligible")

    def _timestamp_failure(self, qualifying: list[LabelDecision]) -> PromotionDecision | None:
        timestamps = [d.timestamp for d in qualifying if d.timestamp is not None]
        if len(timestamps) < 2:
            return PromotionDecision(False, "qualifying decisions missing timestamps")
        span = max(timestamps) - min(timestamps)
        hard_fail = timedelta(seconds=self._config.timestamp_hard_fail_seconds)
        if span > hard_fail:
            return PromotionDecision(False, f"timestamp span {span} exceeds hard fail")
        return None

    def _market_failure(self, qualifying: list[LabelDecision]) -> PromotionDecision | None:
        market_sets = [set(d.market_ids) for d in qualifying]
        if not market_sets:
            return PromotionDecision(False, "qualifying decisions missing markets")
        intersection = set.intersection(*market_sets) if market_sets else set()
        union = set.union(*market_sets) if market_sets else set()
        if not union:
            return PromotionDecision(False, "qualifying decisions list no markets")
        jaccard = len(intersection) / len(union)
        if jaccard <= self._config.market_jaccard_hard_fail:
            return PromotionDecision(False, f"market Jaccard {jaccard:.2f} at or below hard fail")
        return None

    def promotion_warnings(self, candidate_id: str) -> list[str]:
        """Return non-fatal advisory warnings (kept separate from hard fails)."""
        decisions = self._queue.decisions_for(candidate_id)
        qualifying = [d for d in decisions if d.qualifies]
        warnings: list[str] = []
        if qualifying:
            timestamps = [d.timestamp for d in qualifying if d.timestamp is not None]
            if len(timestamps) >= 2:
                span = max(timestamps) - min(timestamps)
                soft_window = timedelta(seconds=self._config.timestamp_agreement_window_seconds)
                if span > soft_window:
                    warnings.append(f"timestamp span {span} exceeds warning window")
            market_sets = [set(d.market_ids) for d in qualifying]
            if market_sets and set.union(*market_sets):
                jaccard = len(set.intersection(*market_sets)) / len(set.union(*market_sets))
                if jaccard < self._config.market_jaccard_target:
                    warnings.append(
                        f"market Jaccard {jaccard:.2f} below target "
                        f"{self._config.market_jaccard_target:.2f}"
                    )
        return warnings
