"""Cluster-level merge over taxonomy-related markets.

Signals of the same type firing within the cluster_window on markets
sharing a strong taxonomy edge (positive, inverse, causal) are merged
into a single cluster signal per docs/architecture/deduplication-and-storms.md
§Cluster-Level Merge. complex and unknown edges do not trigger cluster
merge.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from augur_signals.models import MarketSignal


class TaxonomyEdgesProvider:
    """Adapter the dedup layer uses to look up related markets.

    The context-assembler's MarketTaxonomy satisfies this surface; the
    adapter class keeps the dedup module independent of the taxonomy
    module so circular imports are avoided.
    """

    def __init__(self, edges: Mapping[str, list[tuple[str, str]]]) -> None:
        self._edges = dict(edges)

    def related(self, market_id: str) -> list[tuple[str, str]]:
        """Return the list of `(other_market_id, relationship_type)` edges."""
        return list(self._edges.get(market_id, []))


class ClusterMerge:
    """Merges taxonomy-clustered signals within a rolling time window."""

    def __init__(
        self,
        taxonomy: TaxonomyEdgesProvider,
        window_seconds: int = 90,
        relationship_types: set[str] | None = None,
    ) -> None:
        self._taxonomy = taxonomy
        self._window = timedelta(seconds=window_seconds)
        self._types = set(relationship_types or {"positive", "inverse", "causal"})

    def merge(self, signals: list[MarketSignal]) -> list[MarketSignal]:
        """Group signals by cluster and signal type; collapse each group."""
        if not signals:
            return []
        sorted_signals = sorted(signals, key=lambda s: s.detected_at)
        results: list[MarketSignal] = []
        consumed: set[str] = set()
        for signal in sorted_signals:
            if signal.signal_id in consumed:
                continue
            cluster = self._cluster_for(signal, sorted_signals, consumed)
            if len(cluster) == 1:
                results.append(signal)
                consumed.add(signal.signal_id)
                continue
            representative = _collapse(cluster)
            results.append(representative)
            consumed.update(s.signal_id for s in cluster)
        return results

    def _cluster_for(
        self,
        anchor: MarketSignal,
        signals: list[MarketSignal],
        consumed: set[str],
    ) -> list[MarketSignal]:
        related = {
            market
            for market, relationship in self._taxonomy.related(anchor.market_id)
            if relationship in self._types
        }
        cluster: list[MarketSignal] = [anchor]
        for other in signals:
            if other.signal_id == anchor.signal_id or other.signal_id in consumed:
                continue
            if other.signal_type != anchor.signal_type:
                continue
            if other.market_id not in related:
                continue
            if (
                abs((other.detected_at - anchor.detected_at).total_seconds())
                > self._window.total_seconds()
            ):
                continue
            cluster.append(other)
        return cluster


_TIER_RANK: dict[str, int] = {"high": 3, "mid": 2, "low": 1}


def _collapse(cluster: list[MarketSignal]) -> MarketSignal:
    # Per docs/architecture/deduplication-and-storms.md §Cluster-Level
    # Merge, the representative is the highest-liquidity-tier market in
    # the cluster; ties break alphabetically by market_id.
    top_tier = max(_TIER_RANK.get(s.liquidity_tier, 0) for s in cluster)
    base = min(
        (s for s in cluster if _TIER_RANK.get(s.liquidity_tier, 0) == top_tier),
        key=lambda s: s.market_id,
    )
    magnitude = max(s.magnitude for s in cluster)
    confidence = max(s.confidence for s in cluster)
    manipulation_flags = list({flag for s in cluster for flag in s.manipulation_flags})
    related = sorted(
        {mid for s in cluster for mid in s.related_market_ids}
        | {s.market_id for s in cluster if s.market_id != base.market_id}
    )
    raw_features = dict(base.raw_features)
    raw_features["cluster_member_signal_ids"] = ",".join(sorted(s.signal_id for s in cluster))
    return base.model_copy(
        update={
            "magnitude": magnitude,
            "confidence": confidence,
            "manipulation_flags": manipulation_flags,
            "related_market_ids": related,
            "raw_features": raw_features,
        }
    )
