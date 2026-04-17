"""Tests for the signal-to-event join."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from augur_labels.join.signal_to_event import join_signals_to_events
from augur_labels.models import NewsworthyEvent
from augur_signals.models import MarketSignal, SignalType, new_signal_id


def _signal(
    market_id: str = "kalshi_fed",
    detected_at: datetime | None = None,
) -> MarketSignal:
    return MarketSignal(
        signal_id=new_signal_id(),
        market_id=market_id,
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.8,
        direction=1,
        confidence=0.8,
        fdr_adjusted=False,
        detected_at=detected_at or datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        raw_features={"calibration_provenance": "d@identity_v0"},
    )


def _event(
    event_id: str,
    market_ids: list[str] | None = None,
    ground_truth_offset_hours: float = 1.0,
    status: str = "labeled",
) -> NewsworthyEvent:
    return NewsworthyEvent(
        event_id=event_id,
        ground_truth_timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        + timedelta(hours=ground_truth_offset_hours),
        market_ids=market_ids or ["kalshi_fed"],
        category="monetary_policy",
        headline=f"Event {event_id}",
        source_urls=["https://a", "https://b"],
        source_publishers=["reuters", "bloomberg"],
        labeler_ids=["ann1", "ann2"],
        label_protocol_version="1.0",
        status=status,  # type: ignore[arg-type]
        created_at=datetime(2026, 3, 15, 13, 0, tzinfo=UTC),
    )


@pytest.mark.unit
def test_true_positive_on_event_within_lead_window() -> None:
    labels = join_signals_to_events(
        [_signal()],
        [_event("e1", ground_truth_offset_hours=2.0)],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert len(labels) == 1
    assert labels[0].label == "true_positive"
    assert labels[0].event_id == "e1"
    assert labels[0].lead_time_seconds == 2 * 3600


@pytest.mark.unit
def test_false_positive_when_no_matching_event() -> None:
    labels = join_signals_to_events(
        [_signal()],
        [],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert labels[0].label == "false_positive"
    assert labels[0].event_id is None
    assert labels[0].lead_time_seconds is None


@pytest.mark.unit
def test_false_positive_when_event_outside_lead_window() -> None:
    # Event 48 hours after signal: outside 24h lead window.
    labels = join_signals_to_events(
        [_signal()],
        [_event("e1", ground_truth_offset_hours=48.0)],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert labels[0].label == "false_positive"


@pytest.mark.unit
def test_false_positive_when_event_before_signal() -> None:
    # Signal at 12:00; event at 10:00 (negative lead time).
    labels = join_signals_to_events(
        [_signal()],
        [_event("e1", ground_truth_offset_hours=-2.0)],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert labels[0].label == "false_positive"


@pytest.mark.unit
def test_match_earliest_event_when_multiple_in_window() -> None:
    labels = join_signals_to_events(
        [_signal()],
        [
            _event("e2", ground_truth_offset_hours=6.0),
            _event("e1", ground_truth_offset_hours=1.0),
        ],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert labels[0].event_id == "e1"
    assert labels[0].lead_time_seconds == 3600


@pytest.mark.unit
def test_ignores_candidate_and_superseded_events() -> None:
    labels = join_signals_to_events(
        [_signal()],
        [
            _event("e1", ground_truth_offset_hours=1.0, status="candidate"),
            _event("e2", ground_truth_offset_hours=2.0, status="superseded"),
        ],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert labels[0].label == "false_positive"


@pytest.mark.unit
def test_market_id_mismatch_produces_false_positive() -> None:
    labels = join_signals_to_events(
        [_signal(market_id="kalshi_fed")],
        [_event("e1", market_ids=["polymarket_other"], ground_truth_offset_hours=2.0)],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert labels[0].label == "false_positive"


@pytest.mark.unit
def test_empty_signal_list_returns_empty() -> None:
    assert (
        join_signals_to_events(
            [], [_event("e1")], now=datetime(2026, 3, 16, tzinfo=UTC)
        )
        == []
    )


@pytest.mark.unit
def test_lead_time_boundary_at_zero_is_false_positive() -> None:
    # Signal and event at same instant: lead_time = 0, outside (0, 24h].
    signal_time = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    labels = join_signals_to_events(
        [_signal(detected_at=signal_time)],
        [_event("e1", ground_truth_offset_hours=0.0)],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert labels[0].label == "false_positive"


@pytest.mark.unit
def test_lead_time_boundary_at_24h_is_true_positive() -> None:
    labels = join_signals_to_events(
        [_signal()],
        [_event("e1", ground_truth_offset_hours=24.0)],
        now=datetime(2026, 3, 16, tzinfo=UTC),
    )
    assert labels[0].label == "true_positive"
