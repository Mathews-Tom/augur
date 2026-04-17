"""Tests for the two-annotator workflow enforcer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from augur_labels._config import WorkflowConfig
from augur_labels.annotator.candidate_queue import CandidateQueue
from augur_labels.annotator.workflow import WorkflowEnforcer
from augur_labels.models import EventCandidate, LabelDecision, SourcePublication


def _publication(pub_id: str = "p1") -> SourcePublication:
    return SourcePublication(
        publication_id=pub_id,
        source_id="reuters",
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        headline="h",
        url="https://example.com/story",  # type: ignore[arg-type]
    )


def _candidate(candidate_id: str = "c1") -> EventCandidate:
    return EventCandidate(
        candidate_id=candidate_id,
        discovered_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        publications=[_publication("p1"), _publication("p2")],
        suggested_market_ids=["kalshi_fed"],
    )


def _decision(
    annotator_id: str,
    candidate_id: str = "c1",
    *,
    qualifies: bool = True,
    offset_seconds: int = 0,
    market_ids: list[str] | None = None,
    category: str | None = "monetary_policy",
) -> LabelDecision:
    base = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    return LabelDecision(
        decision_id=f"{annotator_id}-{candidate_id}",
        candidate_id=candidate_id,
        annotator_id=annotator_id,
        decided_at=base,
        qualifies=qualifies,
        timestamp=(base + timedelta(seconds=offset_seconds)) if qualifies else None,
        market_ids=market_ids or (["kalshi_fed"] if qualifies else []),
        category=category if qualifies else None,
    )


@pytest.fixture
def enforcer() -> tuple[WorkflowEnforcer, CandidateQueue]:
    queue = CandidateQueue()
    queue.enqueue([_candidate()])
    return WorkflowEnforcer(WorkflowConfig(), queue), queue


@pytest.mark.unit
def test_cannot_promote_without_any_decisions(
    enforcer: tuple[WorkflowEnforcer, CandidateQueue],
) -> None:
    enf, _ = enforcer
    decision = enf.can_promote("c1")
    assert not decision.allowed
    assert "two distinct" in decision.reason


@pytest.mark.unit
def test_cannot_promote_with_one_annotator(
    enforcer: tuple[WorkflowEnforcer, CandidateQueue],
) -> None:
    enf, queue = enforcer
    queue.record(_decision("ann1"))
    decision = enf.can_promote("c1")
    assert not decision.allowed
    assert "two distinct" in decision.reason


@pytest.mark.unit
def test_cannot_promote_on_existence_disagreement(
    enforcer: tuple[WorkflowEnforcer, CandidateQueue],
) -> None:
    enf, queue = enforcer
    queue.record(_decision("ann1", qualifies=True))
    queue.record(_decision("ann2", qualifies=False))
    decision = enf.can_promote("c1")
    assert not decision.allowed
    assert "disagree" in decision.reason


@pytest.mark.unit
def test_promotion_allowed_when_timestamps_close_and_markets_match(
    enforcer: tuple[WorkflowEnforcer, CandidateQueue],
) -> None:
    enf, queue = enforcer
    queue.record(_decision("ann1", offset_seconds=0))
    queue.record(_decision("ann2", offset_seconds=30))
    decision = enf.can_promote("c1")
    assert decision.allowed


@pytest.mark.unit
def test_promotion_blocked_on_timestamp_hard_fail(
    enforcer: tuple[WorkflowEnforcer, CandidateQueue],
) -> None:
    enf, queue = enforcer
    queue.record(_decision("ann1", offset_seconds=0))
    queue.record(_decision("ann2", offset_seconds=600))  # 10 min > 5 min hard fail
    decision = enf.can_promote("c1")
    assert not decision.allowed
    assert "hard fail" in decision.reason


@pytest.mark.unit
def test_promotion_blocked_on_zero_market_jaccard(
    enforcer: tuple[WorkflowEnforcer, CandidateQueue],
) -> None:
    enf, queue = enforcer
    queue.record(_decision("ann1", market_ids=["a"]))
    queue.record(_decision("ann2", market_ids=["b"]))
    decision = enf.can_promote("c1")
    assert not decision.allowed
    assert "Jaccard" in decision.reason


@pytest.mark.unit
def test_promotion_warnings_fire_below_target(
    enforcer: tuple[WorkflowEnforcer, CandidateQueue],
) -> None:
    enf, queue = enforcer
    queue.record(_decision("ann1", offset_seconds=0, market_ids=["a", "b"]))
    queue.record(_decision("ann2", offset_seconds=90, market_ids=["a", "c"]))
    warnings = enf.promotion_warnings("c1")
    # Timestamp span 90s > 60s warning window; Jaccard = 1/3 < 0.85 target.
    assert any("timestamp span" in w for w in warnings)
    assert any("Jaccard" in w for w in warnings)


@pytest.mark.unit
def test_candidate_queue_rejects_double_decisions_from_same_annotator(
    enforcer: tuple[WorkflowEnforcer, CandidateQueue],
) -> None:
    _, queue = enforcer
    queue.record(_decision("ann1"))
    with pytest.raises(ValueError, match="already decided"):
        queue.record(_decision("ann1"))
