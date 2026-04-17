"""Exact-fingerprint deduplication of raw signals.

Two raw signals are duplicates if they share ``(market_id, signal_type,
time_bucket(detected_at, bucket_seconds))``. Merge rules per
docs/architecture/deduplication-and-storms.md §Signal Fingerprint:
take the max magnitude, max confidence, union of manipulation_flags,
union of related_market_ids, earliest detected_at, smallest
signal_id lexicographically, and record the source signal_ids in
raw_features["merge_provenance"].
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from augur_signals.models import MarketSignal


def _bucket(timestamp: datetime, bucket_seconds: int) -> datetime:
    seconds = (timestamp.second // bucket_seconds) * bucket_seconds
    return timestamp.replace(microsecond=0, second=seconds)


def fingerprint(signal: MarketSignal, bucket_seconds: int = 30) -> tuple[str, str, datetime]:
    """Return the deduplication key for *signal*."""
    return (
        signal.market_id,
        signal.signal_type.value,
        _bucket(signal.detected_at, bucket_seconds),
    )


def _merge_group(signals: list[MarketSignal]) -> MarketSignal:
    """Merge a group of fingerprint-equal signals into one representative."""
    if len(signals) == 1:
        return signals[0]
    base = max(signals, key=lambda s: (s.magnitude, s.confidence))
    magnitude = max(s.magnitude for s in signals)
    confidence = max(s.confidence for s in signals)
    manipulation_flags = list({flag for s in signals for flag in s.manipulation_flags})
    related = list({rid for s in signals for rid in s.related_market_ids})
    earliest = min(s.detected_at for s in signals)
    signal_id = min(s.signal_id for s in signals)
    raw_features = dict(base.raw_features)
    raw_features["merge_provenance"] = ",".join(sorted(s.signal_id for s in signals))
    return base.model_copy(
        update={
            "signal_id": signal_id,
            "magnitude": magnitude,
            "confidence": confidence,
            "manipulation_flags": manipulation_flags,
            "related_market_ids": related,
            "detected_at": earliest,
            "raw_features": raw_features,
        }
    )


def merge(signals: Iterable[MarketSignal], bucket_seconds: int = 30) -> list[MarketSignal]:
    """Apply fingerprint dedup to *signals* and return the compressed list."""
    buckets: dict[tuple[str, str, datetime], list[MarketSignal]] = {}
    for signal in signals:
        key = fingerprint(signal, bucket_seconds)
        buckets.setdefault(key, []).append(signal)
    return [_merge_group(group) for group in buckets.values()]
