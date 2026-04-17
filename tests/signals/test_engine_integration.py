"""End-to-end integration test against a synthetic snapshot stream.

Exercises the full extraction pipeline — normalization, feature
computation, detector dispatch, manipulation evaluation, fingerprint
and cluster dedup, bus publish, and context assembly — without live
API access. Recorded platform fixtures will replace the synthetic
stream once the labeling workstream produces a curated set.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from augur_signals.bus.memory import InProcessAsyncBus
from augur_signals.calibration._config import CalibrationConfig
from augur_signals.calibration.fdr_controller import FDRController
from augur_signals.context.assembler import ContextAssembler
from augur_signals.context.investigation_prompts import InvestigationPromptLibrary
from augur_signals.context.related import RelatedMarketResolver
from augur_signals.context.taxonomy import MarketTaxonomy, TaxonomyEdge
from augur_signals.dedup._config import DedupBody
from augur_signals.dedup.cluster import ClusterMerge, TaxonomyEdgesProvider
from augur_signals.detectors._config import (
    BookImbalanceConfig,
    CrossMarketConfig,
    PriceVelocityConfig,
    RegimeShiftConfig,
    VolumeSpikeConfig,
)
from augur_signals.detectors.book_imbalance import BookImbalanceDetector
from augur_signals.detectors.cross_market import CrossMarketDivergenceDetector
from augur_signals.detectors.price_velocity import PriceVelocityDetector
from augur_signals.detectors.regime_shift import RegimeShiftDetector
from augur_signals.detectors.registry import DetectorRegistry
from augur_signals.detectors.volume_spike import VolumeSpikeDetector
from augur_signals.engine import Engine
from augur_signals.features._config import FeaturePipelineConfig
from augur_signals.features.pipeline import FeaturePipeline
from augur_signals.manipulation._config import ManipulationConfig
from augur_signals.manipulation.detector import ManipulationDetector
from augur_signals.models import MarketSnapshot, SignalType
from augur_signals.storage.duckdb_store import DuckDBStore


def _snapshot(market_id: str, price: float, offset_seconds: int) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        last_price=price,
        bid=max(0.0, price - 0.01),
        ask=min(1.0, price + 0.01),
        spread=0.02,
        volume_24h=200_000.0,
        liquidity=8_000.0,
        question=f"Will {market_id} resolve yes?",
        resolution_source="Source",
        resolution_criteria="Criteria",
        closes_at=datetime(2026, 6, 15, tzinfo=UTC),
        raw_json={},
    )


@pytest.mark.asyncio
async def test_engine_produces_contexts_after_price_shift(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "engine.duckdb")
    store.initialize()
    bus = InProcessAsyncBus(capacity=64)

    registry = DetectorRegistry()
    registry.register(PriceVelocityDetector(PriceVelocityConfig(cooldown_seconds=0)))
    registry.register(VolumeSpikeDetector(VolumeSpikeConfig()))
    registry.register(BookImbalanceDetector(BookImbalanceConfig()))
    registry.register(RegimeShiftDetector(RegimeShiftConfig()))
    fdr = FDRController(CalibrationConfig())
    registry.register_batch(CrossMarketDivergenceDetector(CrossMarketConfig(), fdr, []))

    manipulation = ManipulationDetector(ManipulationConfig())
    taxonomy = MarketTaxonomy([TaxonomyEdge("a", "b", "inverse", 0.9)])
    resolver = RelatedMarketResolver(taxonomy, store)
    library = InvestigationPromptLibrary(
        [(SignalType.PRICE_VELOCITY, "monetary_policy", ["Check FOMC"])]
    )
    assembler = ContextAssembler(store, resolver, library, {"a": "monetary_policy"})

    cluster = ClusterMerge(
        TaxonomyEdgesProvider({"a": [("b", "inverse")], "b": [("a", "inverse")]}),
        window_seconds=DedupBody().cluster_window_seconds,
    )
    engine = Engine(
        store=store,
        registry=registry,
        manipulation=manipulation,
        cluster=cluster,
        bus=bus,
        assembler=assembler,
    )

    pipeline = FeaturePipeline(FeaturePipelineConfig(warmup_size=5))
    contexts_emitted: list[str] = []
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    # Warmup flat phase — long enough that the price-velocity detector
    # crosses its own internal warmup threshold with features available.
    for i in range(80):
        snap = _snapshot("a", price=0.5, offset_seconds=i * 30)
        feature = pipeline.ingest(snap)
        features = {"a": feature} if feature else {}
        contexts = await engine.run_cycle(
            snapshots=[snap],
            features=features,
            recent_trades={},
            recent_book_events={},
            now=now + timedelta(seconds=i * 30),
        )
        contexts_emitted.extend(ctx.signal.signal_id for ctx in contexts)
    # Step change — sustained level shift over enough ticks for BOCPD
    # to concentrate run-length mass below the fire threshold.
    for i in range(80, 160):
        snap = _snapshot("a", price=0.85, offset_seconds=i * 30)
        feature = pipeline.ingest(snap)
        features = {"a": feature} if feature else {}
        contexts = await engine.run_cycle(
            snapshots=[snap],
            features=features,
            recent_trades={},
            recent_book_events={},
            now=now + timedelta(seconds=i * 30),
        )
        contexts_emitted.extend(ctx.signal.signal_id for ctx in contexts)

    # The price velocity detector should have fired at least once.
    assert len(contexts_emitted) >= 1
    store.close()
