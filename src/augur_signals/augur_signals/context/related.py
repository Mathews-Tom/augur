"""Related-market resolver for the context assembler.

For each taxonomy edge emanating from a signal's market, look up the
most-recent snapshot in the store and compute the 24 h delta.
Markets without a recent snapshot are omitted and logged.
"""

from __future__ import annotations

from datetime import timedelta

from augur_signals.context.taxonomy import MarketTaxonomy
from augur_signals.models import RelatedMarketState
from augur_signals.storage.duckdb_store import DuckDBStore


class RelatedMarketResolver:
    """Resolves related-market state at assembly time."""

    def __init__(
        self,
        taxonomy: MarketTaxonomy,
        store: DuckDBStore,
        delta_window_seconds: int = 86_400,
    ) -> None:
        self._taxonomy = taxonomy
        self._store = store
        # Window over which to compute delta_24h against the most-recent
        # snapshot. The default matches the field's semantics in
        # docs/contracts/schema-and-versioning.md §RelatedMarketState.
        self._delta_window = timedelta(seconds=delta_window_seconds)

    def resolve(self, market_id: str) -> list[RelatedMarketState]:
        edges = self._taxonomy.edges_for(market_id)
        results: list[RelatedMarketState] = []
        for edge in edges:
            snap = self._store.latest_snapshot(edge.market_b)
            if snap is None:
                continue
            # Fetch the oldest in-window snapshot for the delta.
            prior_end = snap.timestamp
            prior_start = prior_end - self._delta_window
            window = self._store.snapshots_in_window(edge.market_b, prior_start, prior_end)
            prior_price = window[0].last_price if window else snap.last_price
            delta_24h = snap.last_price - prior_price
            results.append(
                RelatedMarketState(
                    market_id=snap.market_id,
                    question=snap.question,
                    current_price=snap.last_price,
                    delta_24h=delta_24h,
                    volume_24h=snap.volume_24h,
                    relationship_type=edge.relationship_type,
                    relationship_strength=edge.strength,
                )
            )
        return results
