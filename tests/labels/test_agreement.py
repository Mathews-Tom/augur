"""Tests for inter-annotator agreement metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from augur_labels.annotator.agreement import compute_agreement
from augur_labels.models import LabelDecision


def _decision(
    annotator_id: str,
    candidate_id: str,
    *,
    qualifies: bool = True,
    timestamp_offset_seconds: int = 0,
    market_ids: list[str] | None = None,
    category: str | None = "monetary_policy",
) -> LabelDecision:
    base = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    ts = base + timedelta(seconds=timestamp_offset_seconds) if qualifies else None
    resolved_markets = (market_ids or []) if qualifies else []
    resolved_category = category if qualifies else None
    return LabelDecision(
        decision_id=f"{annotator_id}-{candidate_id}",
        candidate_id=candidate_id,
        annotator_id=annotator_id,
        decided_at=base,
        qualifies=qualifies,
        timestamp=ts,
        market_ids=resolved_markets,
        category=resolved_category,
    )


@pytest.mark.unit
def test_perfect_agreement_meets_all_targets() -> None:
    decisions_a = [
        _decision("ann1", "c1", market_ids=["kalshi_fed"]),
        _decision("ann1", "c2", market_ids=["kalshi_fed", "polymarket_a"]),
    ]
    decisions_b = [
        _decision("ann2", "c1", market_ids=["kalshi_fed"]),
        _decision("ann2", "c2", market_ids=["kalshi_fed", "polymarket_a"]),
    ]
    report = compute_agreement(
        decisions_a,
        decisions_b,
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert report.event_existence_kappa == pytest.approx(1.0)
    assert report.timestamp_agreement_60s == pytest.approx(1.0)
    assert report.market_association_jaccard_mean == pytest.approx(1.0)
    assert report.category_assignment_kappa == pytest.approx(1.0)
    assert report.meets_targets


@pytest.mark.unit
def test_disagreement_on_event_existence_fails_targets() -> None:
    decisions_a = [
        _decision("ann1", "c1", qualifies=True),
        _decision("ann1", "c2", qualifies=True),
    ]
    decisions_b = [
        _decision("ann2", "c1", qualifies=False),
        _decision("ann2", "c2", qualifies=False),
    ]
    report = compute_agreement(
        decisions_a,
        decisions_b,
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert report.event_existence_kappa < 0.95
    assert not report.meets_targets


@pytest.mark.unit
def test_timestamp_within_60_seconds_counts_as_agreement() -> None:
    decisions_a = [
        _decision("ann1", "c1", timestamp_offset_seconds=0, market_ids=["m"]),
    ]
    decisions_b = [
        _decision("ann2", "c1", timestamp_offset_seconds=45, market_ids=["m"]),
    ]
    report = compute_agreement(
        decisions_a,
        decisions_b,
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert report.timestamp_agreement_60s == pytest.approx(1.0)


@pytest.mark.unit
def test_timestamp_over_60_seconds_is_disagreement() -> None:
    decisions_a = [
        _decision("ann1", "c1", timestamp_offset_seconds=0, market_ids=["m"]),
    ]
    decisions_b = [
        _decision("ann2", "c1", timestamp_offset_seconds=120, market_ids=["m"]),
    ]
    report = compute_agreement(
        decisions_a,
        decisions_b,
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert report.timestamp_agreement_60s == pytest.approx(0.0)


@pytest.mark.unit
def test_market_jaccard_partial_overlap() -> None:
    decisions_a = [_decision("ann1", "c1", market_ids=["a", "b"])]
    decisions_b = [_decision("ann2", "c1", market_ids=["a", "c"])]
    report = compute_agreement(
        decisions_a,
        decisions_b,
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 31, tzinfo=UTC),
    )
    # Jaccard = |a| ∩ |a,c| / |a,b,c| = 1/3.
    assert report.market_association_jaccard_mean == pytest.approx(1.0 / 3.0)


@pytest.mark.unit
def test_empty_pair_returns_zero_metrics() -> None:
    report = compute_agreement(
        [],
        [],
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert report.candidate_count == 0
    assert not report.meets_targets
