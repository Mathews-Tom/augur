"""Subject naming helpers matching `.docs/phase-5-scaling.md §4.3`.

A single module owns the subject strings so producers and consumers
stay aligned. Every helper returns a full subject with the configured
prefix so callers pass the result straight into ``bus.publish`` /
``bus.subscribe``.
"""

from __future__ import annotations


def snapshots(prefix: str, platform: str, market_id: str) -> str:
    return f"{prefix}.snapshots.{platform}.{market_id}"


def snapshots_pattern(prefix: str, platform: str | None = None) -> str:
    """Wildcard pattern for a feature worker to consume.

    If *platform* is None the pattern matches every platform; otherwise
    it narrows to the named platform.
    """
    if platform is None:
        return f"{prefix}.snapshots.>"
    return f"{prefix}.snapshots.{platform}.>"


def features(prefix: str, market_id: str) -> str:
    return f"{prefix}.features.{market_id}"


def features_pattern(prefix: str) -> str:
    return f"{prefix}.features.>"


def candidates(prefix: str, detector_id: str) -> str:
    return f"{prefix}.candidates.{detector_id}"


def candidates_pattern(prefix: str) -> str:
    return f"{prefix}.candidates.>"


def flagged_signals(prefix: str) -> str:
    return f"{prefix}.flagged_signals"


def calibrated_signals(prefix: str) -> str:
    return f"{prefix}.calibrated_signals"


def signals(prefix: str) -> str:
    return f"{prefix}.signals"


def contexts(prefix: str) -> str:
    return f"{prefix}.contexts"


def briefs(prefix: str, fmt: str) -> str:
    return f"{prefix}.briefs.{fmt}"


def ops_events(prefix: str) -> str:
    return f"{prefix}.ops.events"
