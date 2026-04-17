"""Pure-function manipulation signature checks.

Each function consumes primitives (trades, book events, snapshots) and
returns a boolean or numeric score without side effects. Authoritative
semantics live in docs/methodology/manipulation-taxonomy.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from augur_signals.ingestion.base import RawTrade
from augur_signals.models import MarketSnapshot


@dataclass(frozen=True, slots=True)
class BookEvent:
    """A single order-book mutation — insert, cancel, or replace."""

    market_id: str
    timestamp: datetime
    kind: str
    size: float


def single_counterparty_concentration(trades: Sequence[RawTrade]) -> float:
    """Return the Herfindahl index of trade volume by counterparty.

    Counterparty identifiers are preserved verbatim from the platform;
    unknown counterparties are bucketed under a synthetic "_unknown"
    key so the index still reflects concentration within the known
    subset without over-weighting anonymous volume.
    """
    if not trades:
        return 0.0
    volumes: dict[str, float] = {}
    for trade in trades:
        key = trade.counterparty or "_unknown"
        volumes[key] = volumes.get(key, 0.0) + trade.size
    total = sum(volumes.values())
    if total <= 0.0:
        return 0.0
    shares = [v / total for v in volumes.values()]
    return sum(s * s for s in shares)


def size_vs_depth_outlier(
    trade: RawTrade,
    prior_book_depth: float,
    threshold_ratio: float,
) -> bool:
    """True when a single trade consumed more than `threshold_ratio` of depth."""
    if prior_book_depth <= 0.0:
        return False
    return (trade.size / prior_book_depth) > threshold_ratio


def cancel_replace_burst(
    book_events: Sequence[BookEvent],
    window_seconds: int,
    min_count: int,
) -> bool:
    """True when cancel+replace event count exceeds the threshold in the window."""
    if not book_events or min_count <= 0:
        return False
    sorted_events = sorted(
        (e for e in book_events if e.kind in {"cancel", "replace"}),
        key=lambda e: e.timestamp,
    )
    if len(sorted_events) < min_count:
        return False
    # Sliding window in seconds over sorted events.
    left = 0
    for right, event in enumerate(sorted_events):
        while (
            left <= right
            and (event.timestamp - sorted_events[left].timestamp).total_seconds() > window_seconds
        ):
            left += 1
        if right - left + 1 >= min_count:
            return True
    return False


def thin_book_during_move(
    snapshots: Sequence[MarketSnapshot],
    min_depth_dollars: float,
) -> bool:
    """True when the median book depth over the window falls below the floor."""
    if not snapshots:
        return False
    depths = sorted(snap.liquidity for snap in snapshots)
    median = depths[len(depths) // 2]
    return median < min_depth_dollars


def pre_resolution_window(
    signal_detected_at: datetime,
    market_closes_at: datetime | None,
    window_seconds: int = 21_600,
) -> bool:
    """True when the signal fired within *window_seconds* of market close."""
    if market_closes_at is None:
        return False
    delta = (market_closes_at - signal_detected_at).total_seconds()
    return 0.0 <= delta < window_seconds
