"""Pure feature-computation functions over a snapshot window.

Every function takes a sequence of MarketSnapshot and returns a float
or None when the window is underdetermined. Pure determinism is load-
bearing for replay fidelity: the same buffer in always produces the
same vector out.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from augur_signals.models import MarketSnapshot


def price_momentum(snapshots: Sequence[MarketSnapshot]) -> float:
    """Return the fractional change in price over the window."""
    if len(snapshots) < 2:
        return 0.0
    start = snapshots[0].last_price
    end = snapshots[-1].last_price
    if start <= 0.0:
        return 0.0
    return (end - start) / start


def volatility(snapshots: Sequence[MarketSnapshot]) -> float:
    """Return the sample standard deviation of log returns."""
    if len(snapshots) < 3:
        return 0.0
    returns: list[float] = []
    for prev, curr in pairwise(snapshots):
        if prev.last_price <= 0.0 or curr.last_price <= 0.0:
            continue
        returns.append(math.log(curr.last_price / prev.last_price))
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance)


def volume_ratio(
    snapshots: Sequence[MarketSnapshot],
    ewma_baseline: float,
) -> float:
    """Window volume divided by the per-market EWMA baseline.

    Returns 1.0 when the baseline has not yet accumulated meaningful
    history; callers enforce their own liquidity floors before acting
    on the ratio.
    """
    if not snapshots or ewma_baseline <= 0.0:
        return 1.0
    window_total = sum(snap.volume_24h for snap in snapshots)
    return window_total / (ewma_baseline * len(snapshots))


def bid_ask_ratio(snapshot: MarketSnapshot) -> float | None:
    """bid / (bid + ask). None when either side is missing."""
    if snapshot.bid is None or snapshot.ask is None:
        return None
    total = snapshot.bid + snapshot.ask
    if total <= 0.0:
        return None
    return snapshot.bid / total


def spread_pct(snapshot: MarketSnapshot) -> float | None:
    """(ask - bid) / midpoint. None when either side is missing."""
    if snapshot.bid is None or snapshot.ask is None:
        return None
    midpoint = (snapshot.bid + snapshot.ask) / 2.0
    if midpoint <= 0.0:
        return None
    return (snapshot.ask - snapshot.bid) / midpoint
