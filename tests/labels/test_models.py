"""Tests for the labeling pipeline data contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from augur_labels.models import (
    AgreementReport,
    AnnotatorIdentity,
    EventCandidate,
    LabelDecision,
    NewsworthyEvent,
    QualifyingSource,
    SourcePublication,
)


def _publication(pub_id: str = "p1", source_id: str = "reuters") -> SourcePublication:
    return SourcePublication(
        publication_id=pub_id,
        source_id=source_id,  # type: ignore[arg-type]
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        headline="Fed holds rates",
        url="https://example.com/story",  # type: ignore[arg-type]
        body_excerpt="The Federal Reserve left rates unchanged.",
        keywords=["fed", "rates"],
    )


@pytest.mark.unit
def test_qualifying_source_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        QualifyingSource(source_id="nyt", name="New York Times")  # type: ignore[arg-type]


@pytest.mark.unit
def test_source_publication_preserves_keywords_and_excerpt() -> None:
    pub = _publication()
    assert pub.keywords == ["fed", "rates"]
    assert pub.body_excerpt is not None


@pytest.mark.unit
def test_event_candidate_holds_multiple_publications() -> None:
    cand = EventCandidate(
        candidate_id="c1",
        discovered_at=datetime(2026, 3, 15, 12, 5, tzinfo=UTC),
        publications=[_publication("p1", "reuters"), _publication("p2", "bloomberg")],
        suggested_market_ids=["kalshi_fed"],
    )
    assert len(cand.publications) == 2
    assert {p.source_id for p in cand.publications} == {"reuters", "bloomberg"}


@pytest.mark.unit
def test_newsworthy_event_accepts_protocol_fields() -> None:
    event = NewsworthyEvent(
        event_id="e1",
        ground_truth_timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        market_ids=["kalshi_fed"],
        category="monetary_policy",
        headline="Fed holds rates",
        source_urls=["https://a", "https://b"],
        source_publishers=["reuters", "bloomberg"],
        labeler_ids=["ann1", "ann2"],
        label_protocol_version="1.0",
        status="labeled",
        created_at=datetime(2026, 3, 15, 13, 0, tzinfo=UTC),
    )
    assert event.status == "labeled"
    assert event.corrects is None


@pytest.mark.unit
def test_newsworthy_event_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        NewsworthyEvent(
            event_id="e1",
            ground_truth_timestamp=datetime(2026, 3, 15, tzinfo=UTC),
            market_ids=["m"],
            category="monetary_policy",
            headline="h",
            source_urls=["https://a"],
            source_publishers=["reuters"],
            labeler_ids=["a"],
            label_protocol_version="1.0",
            status="draft",  # type: ignore[arg-type]
            created_at=datetime(2026, 3, 15, tzinfo=UTC),
        )


@pytest.mark.unit
def test_label_decision_qualifies_without_timestamp_by_default() -> None:
    decision = LabelDecision(
        decision_id="d1",
        candidate_id="c1",
        annotator_id="ann1",
        decided_at=datetime(2026, 3, 15, 13, 0, tzinfo=UTC),
        qualifies=False,
    )
    assert decision.timestamp is None
    assert decision.market_ids == []


@pytest.mark.unit
def test_annotator_identity_accepts_optional_display_name() -> None:
    id1 = AnnotatorIdentity(annotator_id="ann1")
    id2 = AnnotatorIdentity(annotator_id="ann1", display_name="Annotator 1")
    assert id1.display_name is None
    assert id2.display_name == "Annotator 1"


@pytest.mark.unit
def test_agreement_report_structure() -> None:
    report = AgreementReport(
        annotator_pair=("ann1", "ann2"),
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 31, tzinfo=UTC),
        candidate_count=10,
        event_existence_kappa=0.97,
        timestamp_agreement_60s=0.95,
        market_association_jaccard_mean=0.88,
        category_assignment_kappa=0.92,
        meets_targets=True,
    )
    assert report.meets_targets is True
