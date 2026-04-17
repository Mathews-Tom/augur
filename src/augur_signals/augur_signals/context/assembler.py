"""Deterministic context assembler.

Wraps a MarketSignal with verbatim platform metadata, related-market
state, and curated investigation prompts. The assembler is a pure
function of (signal, metadata store, taxonomy, prompt library). Two
invocations with identical inputs must produce byte-identical JSON —
the determinism test exercises this invariant.
"""

from __future__ import annotations

from augur_signals.context.investigation_prompts import InvestigationPromptLibrary
from augur_signals.context.related import RelatedMarketResolver
from augur_signals.models import (
    InterpretationMode,
    MarketSignal,
    SignalContext,
)
from augur_signals.storage.duckdb_store import DuckDBStore


class MissingMetadataError(RuntimeError):
    """Raised when the metadata store has no snapshot for the signal's market."""


class ContextAssembler:
    """Produces SignalContext envelopes deterministically."""

    def __init__(
        self,
        store: DuckDBStore,
        related_resolver: RelatedMarketResolver,
        prompt_library: InvestigationPromptLibrary,
        category_of: dict[str, str] | None = None,
    ) -> None:
        self._store = store
        self._related = related_resolver
        self._prompts = prompt_library
        self._category_of = dict(category_of or {})

    def register_category(self, market_id: str, category: str) -> None:
        """Map a market to its taxonomy category for prompt lookup."""
        self._category_of[market_id] = category

    def assemble(self, signal: MarketSignal) -> SignalContext:
        snapshot = self._store.latest_snapshot(signal.market_id)
        if snapshot is None:
            raise MissingMetadataError(f"No snapshot stored for market_id={signal.market_id}")
        if snapshot.closes_at is None:
            raise MissingMetadataError(f"Snapshot for {signal.market_id} is missing closes_at")
        category = self._category_of.get(signal.market_id, "")
        prompts = tuple(self._prompts.lookup(signal.signal_type, category))
        related = tuple(self._related.resolve(signal.market_id))
        return SignalContext(
            signal=signal,
            market_question=snapshot.question,
            resolution_criteria=snapshot.resolution_criteria or "",
            resolution_source=snapshot.resolution_source or "",
            closes_at=snapshot.closes_at,
            related_markets=list(related),
            investigation_prompts=list(prompts),
            interpretation_mode=InterpretationMode.DETERMINISTIC,
        )
