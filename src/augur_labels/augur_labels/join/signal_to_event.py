"""Produce SignalLabel rows by joining signals to newsworthy events.

Implements the true-positive criteria in
docs/methodology/labeling-protocol.md §True Positive Criteria: a
signal is a TP against an event iff the signal's market_id is in
event.market_ids AND the lead time (event.ground_truth_timestamp -
signal.detected_at) lies in (0, lead_window]. Signals matching no
event under this rule are false positives.

Calibration consumes SignalLabel rows via the Phase-1 EmpiricalFPR
and ReliabilityAnalyzer modules; the join runs nightly as part of
scripts/calibrate.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from augur_labels.models import NewsworthyEvent
from augur_signals.models import MarketSignal


@dataclass(frozen=True, slots=True)
class SignalLabel:
    """One signal's TP/FP/TN classification against the labeled corpus."""

    signal_id: str
    event_id: str | None
    label: Literal["true_positive", "false_positive", "true_negative"]
    lead_time_seconds: int | None
    labeled_at: datetime
    label_protocol_version: str


def join_signals_to_events(
    signals: Sequence[MarketSignal],
    events: Sequence[NewsworthyEvent],
    now: datetime,
    lead_window: timedelta = timedelta(hours=24),
    label_protocol_version: str = "1.0",
) -> list[SignalLabel]:
    """Return one SignalLabel per signal.

    Multiple events on the same market within the lead window: the
    signal is labeled against the earliest qualifying event (per the
    protocol's preference for earliest-qualifying-publication timing).
    """
    # Bucket events by market_id so each signal does a single lookup.
    events_by_market: dict[str, list[NewsworthyEvent]] = {}
    for event in events:
        if event.status != "labeled":
            continue
        for market_id in event.market_ids:
            events_by_market.setdefault(market_id, []).append(event)
    for bucket in events_by_market.values():
        bucket.sort(key=lambda e: e.ground_truth_timestamp)

    labels: list[SignalLabel] = []
    for signal in signals:
        candidates = events_by_market.get(signal.market_id, [])
        matched = _earliest_match(signal, candidates, lead_window)
        if matched is None:
            labels.append(
                SignalLabel(
                    signal_id=signal.signal_id,
                    event_id=None,
                    label="false_positive",
                    lead_time_seconds=None,
                    labeled_at=now,
                    label_protocol_version=label_protocol_version,
                )
            )
            continue
        lead = (matched.ground_truth_timestamp - signal.detected_at).total_seconds()
        labels.append(
            SignalLabel(
                signal_id=signal.signal_id,
                event_id=matched.event_id,
                label="true_positive",
                lead_time_seconds=int(lead),
                labeled_at=now,
                label_protocol_version=label_protocol_version,
            )
        )
    return labels


def _earliest_match(
    signal: MarketSignal,
    candidates: Sequence[NewsworthyEvent],
    lead_window: timedelta,
) -> NewsworthyEvent | None:
    max_seconds = lead_window.total_seconds()
    for event in candidates:
        delta = (event.ground_truth_timestamp - signal.detected_at).total_seconds()
        if 0.0 < delta <= max_seconds:
            return event
    return None
