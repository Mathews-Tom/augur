"""Engine orchestrator composing the extraction pipeline.

Composes normalized snapshot -> feature pipeline -> detector dispatch ->
manipulation detector -> dedup -> bus -> context assembler. The
orchestrator is single-process; the multi-process runtime swaps the
bus and storage adapters without touching this module.

`now` threads through every downstream call as a parameter so the
backtest harness and the live engine traverse the same code with
deterministic timing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from augur_signals.bus.memory import InProcessAsyncBus
from augur_signals.context.assembler import ContextAssembler
from augur_signals.dedup.cluster import ClusterMerge
from augur_signals.dedup.fingerprint import merge as fingerprint_merge
from augur_signals.detectors.registry import DetectorRegistry
from augur_signals.ingestion.base import RawTrade
from augur_signals.manipulation.detector import ManipulationDetector, attach_flags
from augur_signals.manipulation.signatures import BookEvent
from augur_signals.models import (
    FeatureVector,
    MarketSignal,
    MarketSnapshot,
    SignalContext,
)
from augur_signals.storage.duckdb_store import DuckDBStore


class Engine:
    """Single-cycle orchestrator that lets the caller drive time."""

    def __init__(
        self,
        store: DuckDBStore,
        registry: DetectorRegistry,
        manipulation: ManipulationDetector,
        cluster: ClusterMerge,
        bus: InProcessAsyncBus,
        assembler: ContextAssembler,
    ) -> None:
        self._store = store
        self._registry = registry
        self._manipulation = manipulation
        self._cluster = cluster
        self._bus = bus
        self._assembler = assembler

    async def run_cycle(
        self,
        snapshots: Sequence[MarketSnapshot],
        features: dict[str, FeatureVector],
        recent_trades: dict[str, Sequence[RawTrade]],
        recent_book_events: dict[str, Sequence[BookEvent]],
        now: datetime,
    ) -> list[SignalContext]:
        """Run one polling cycle end-to-end and return emitted contexts."""
        per_market_signals: list[MarketSignal] = []
        snapshot_index = {snap.market_id: snap for snap in snapshots}
        for snap in snapshots:
            self._store.insert_snapshot(snap)
            feature = features.get(snap.market_id)
            if feature is None:
                continue
            candidates = self._registry.dispatch(snap.market_id, feature, snap, now)
            for candidate in candidates:
                flags = self._manipulation.evaluate(
                    candidate,
                    recent_trades.get(snap.market_id, []),
                    recent_book_events.get(snap.market_id, []),
                    [snap],
                    snap.closes_at,
                )
                per_market_signals.append(attach_flags(candidate, flags))

        batch = self._registry.dispatch_batch(snapshot_index, now)
        for candidate in batch:
            flags = self._manipulation.evaluate(
                candidate,
                recent_trades.get(candidate.market_id, []),
                recent_book_events.get(candidate.market_id, []),
                [snapshot_index[candidate.market_id]],
                snapshot_index[candidate.market_id].closes_at,
            )
            per_market_signals.append(attach_flags(candidate, flags))

        fingerprinted = fingerprint_merge(per_market_signals)
        clustered = self._cluster.merge(fingerprinted)
        contexts: list[SignalContext] = []
        for signal in clustered:
            self._store.insert_signal(signal)
            await self._bus.publish(signal)
            contexts.append(self._assembler.assemble(signal))
        return contexts
