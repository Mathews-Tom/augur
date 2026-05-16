"""Run Augur's single-process live extraction engine."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

from augur_format.deterministic.json_feed import to_canonical_json
from augur_signals._config import load_config
from augur_signals.bus.memory import InProcessAsyncBus
from augur_signals.calibration._config import CalibrationConfig
from augur_signals.calibration.fdr_controller import FDRController
from augur_signals.context.assembler import ContextAssembler
from augur_signals.context.investigation_prompts import InvestigationPromptLibrary
from augur_signals.context.related import RelatedMarketResolver
from augur_signals.context.taxonomy import MarketTaxonomy
from augur_signals.dedup._config import DedupConfig
from augur_signals.dedup.cluster import ClusterMerge, TaxonomyEdgesProvider
from augur_signals.detectors._config import DetectorsConfig
from augur_signals.detectors.book_imbalance import BookImbalanceDetector
from augur_signals.detectors.cross_market import CrossMarketDivergenceDetector
from augur_signals.detectors.price_velocity import PriceVelocityDetector
from augur_signals.detectors.regime_shift import RegimeShiftDetector
from augur_signals.detectors.registry import DetectorRegistry
from augur_signals.detectors.volume_spike import VolumeSpikeDetector
from augur_signals.engine import Engine
from augur_signals.features._config import FeaturePipelineConfig
from augur_signals.features.pipeline import FeaturePipeline
from augur_signals.ingestion.base import AbstractPoller, RawMarketData, RawTrade
from augur_signals.ingestion.kalshi import KalshiPoller
from augur_signals.ingestion.normalizer import normalize
from augur_signals.ingestion.polymarket import PolymarketPoller, primary_clob_token_id
from augur_signals.manipulation._config import ManipulationConfig
from augur_signals.manipulation.detector import ManipulationDetector
from augur_signals.models import FeatureVector, MarketSnapshot
from augur_signals.storage._config import StorageConfig
from augur_signals.storage.factory import make_duckdb_store


class MarketEntry(BaseModel):
    """One configured watchlist market."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    platform: Literal["polymarket", "kalshi"]
    platform_market_id: str
    category: str
    active: bool
    poll_priority: Literal["hot", "warm", "cool", "cold", "normal"] = "normal"


class RelationshipEntry(BaseModel):
    """One curated relationship edge from markets.toml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_a: str
    market_b: str
    type: Literal["positive", "inverse", "complex", "causal"]
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Literal["manual", "embedding"] = "manual"


class MarketsConfig(BaseModel):
    """Top-level markets.toml schema used by the monolith runner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    markets: list[MarketEntry] = Field(default_factory=list)
    relationships: list[RelationshipEntry] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    config_dir: Path
    data_dir: Path
    once: bool
    poll_seconds: float
    trade_lookback_seconds: int


@dataclass(slots=True)
class EngineRuntime:
    engine: Engine
    feature_pipeline: FeaturePipeline
    feature_config: FeaturePipelineConfig
    storage_label: str
    markets: list[MarketEntry]


@dataclass(frozen=True, slots=True)
class CycleSummary:
    storage: str
    active_markets: int
    platforms: tuple[str, ...]
    snapshots: int
    trades: int
    features: int
    signals: int
    feature_warmup_size: int


def _parse_args(argv: Sequence[str]) -> RuntimeConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(os.environ.get("AUGUR_CONFIG_DIR", "config")),
        help="Directory containing Augur TOML config files.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory containing data/investigation_prompts.toml.",
    )
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit.")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=60.0,
        help="Sleep interval between cycles when --once is not set.",
    )
    parser.add_argument(
        "--trade-lookback-seconds",
        type=int,
        default=300,
        help="Initial trade lookback window for manipulation checks.",
    )
    args = parser.parse_args(argv)
    return RuntimeConfig(
        config_dir=args.config_dir,
        data_dir=args.data_dir,
        once=args.once,
        poll_seconds=args.poll_seconds,
        trade_lookback_seconds=args.trade_lookback_seconds,
    )


def _build_registry(config: DetectorsConfig) -> DetectorRegistry:
    registry = DetectorRegistry()
    registry.register(PriceVelocityDetector(config.price_velocity))
    registry.register(VolumeSpikeDetector(config.volume_spike))
    registry.register(BookImbalanceDetector(config.book_imbalance))
    registry.register(RegimeShiftDetector(config.regime_shift))
    registry.register_batch(
        CrossMarketDivergenceDetector(
            config.cross_market,
            FDRController(CalibrationConfig()),
            related_pairs=[],
        )
    )
    return registry


def _build_cluster(config_dir: Path, dedup: DedupConfig) -> ClusterMerge:
    taxonomy = MarketTaxonomy.from_toml(config_dir / "markets.toml")
    edges = {
        market_id: [
            (edge.market_b, edge.relationship_type) for edge in taxonomy.edges_for(market_id)
        ]
        for market_id in _taxonomy_market_ids(taxonomy, config_dir)
    }
    return ClusterMerge(
        TaxonomyEdgesProvider(edges),
        window_seconds=dedup.dedup.cluster_window_seconds,
        relationship_types=set(dedup.dedup.cluster_relationship_types),
    )


def _taxonomy_market_ids(taxonomy: MarketTaxonomy, config_dir: Path) -> set[str]:
    config = load_config(config_dir / "markets.toml", MarketsConfig)
    market_ids = {market.id for market in config.markets}
    for relationship in config.relationships:
        market_ids.add(relationship.market_a)
        market_ids.add(relationship.market_b)
    return {market_id for market_id in market_ids if taxonomy.edges_for(market_id)}


def _build_runtime(config: RuntimeConfig) -> EngineRuntime:
    markets_config = load_config(config.config_dir / "markets.toml", MarketsConfig)
    active = [market for market in markets_config.markets if market.active]
    if not active:
        raise RuntimeError("config/markets.toml has no active markets")
    detector_config = load_config(config.config_dir / "detectors.toml", DetectorsConfig)
    dedup_config = load_config(config.config_dir / "dedup.toml", DedupConfig)
    storage_config = load_config(config.config_dir / "storage.toml", StorageConfig)
    store = make_duckdb_store(storage_config)
    store.initialize()
    feature_config = FeaturePipelineConfig()
    taxonomy = MarketTaxonomy.from_toml(config.config_dir / "markets.toml")
    resolver = RelatedMarketResolver(taxonomy, store)
    prompt_library = InvestigationPromptLibrary.from_toml(
        config.data_dir / "investigation_prompts.toml"
    )
    category_by_market = {market.id: market.category for market in active}
    engine = Engine(
        store=store,
        registry=_build_registry(detector_config),
        manipulation=ManipulationDetector(ManipulationConfig()),
        cluster=_build_cluster(config.config_dir, dedup_config),
        bus=InProcessAsyncBus(capacity=dedup_config.dedup.bus.queue_capacity),
        assembler=ContextAssembler(store, resolver, prompt_library, category_by_market),
    )
    return EngineRuntime(
        engine=engine,
        feature_pipeline=FeaturePipeline(feature_config),
        feature_config=feature_config,
        storage_label=_storage_label(storage_config),
        markets=active,
    )


def _storage_label(config: StorageConfig) -> str:
    if config.backend.kind == "duckdb":
        return f"duckdb:{config.backend.duckdb_path}"
    return f"timescaledb:${config.backend.timescale_url_env}"


def _required_platforms(markets: Sequence[MarketEntry]) -> set[str]:
    return {market.platform for market in markets}


def _build_pollers(
    session: aiohttp.ClientSession,
    markets: Sequence[MarketEntry],
) -> dict[str, AbstractPoller]:
    platforms = _required_platforms(markets)
    pollers: dict[str, AbstractPoller] = {}
    if "polymarket" in platforms:
        pollers["polymarket"] = PolymarketPoller(session)
    if "kalshi" in platforms:
        pollers["kalshi"] = KalshiPoller(session)
    return pollers


async def _fetch_cycle(
    pollers: dict[str, AbstractPoller],
    markets: Sequence[MarketEntry],
    since: datetime,
) -> tuple[list[MarketSnapshot], dict[str, list[RawTrade]]]:
    snapshots: list[MarketSnapshot] = []
    trades: dict[str, list[RawTrade]] = {}
    for market in markets:
        raw = await _poll_configured_market(pollers[market.platform], market)
        book_market_id = _orderbook_market_id(raw, market)
        book = await pollers[market.platform].poll_orderbook(book_market_id)
        snapshot = normalize(raw, book)
        snapshots.append(snapshot)
        raw_trades = await pollers[market.platform].poll_trades(market.platform_market_id, since)
        trades[market.id] = [_remap_trade(trade, market.id) for trade in raw_trades]
    return snapshots, trades


async def _poll_markets_by_platform(
    pollers: dict[str, AbstractPoller],
) -> dict[str, list[RawMarketData]]:
    results: dict[str, list[RawMarketData]] = {}
    for platform, poller in pollers.items():
        results[platform] = await poller.poll_markets()
    return results


async def _poll_configured_market(poller: AbstractPoller, market: MarketEntry) -> RawMarketData:
    if isinstance(poller, PolymarketPoller):
        raw = await poller.poll_market(market.platform_market_id)
        return _remap_raw_market(raw, market.id)
    raw_by_platform = await poller.poll_markets()
    return _select_market(raw_by_platform, market)


def _orderbook_market_id(raw: RawMarketData, market: MarketEntry) -> str:
    if market.platform == "polymarket":
        return primary_clob_token_id(raw)
    return market.platform_market_id


def _select_market(raw_markets: Sequence[RawMarketData], market: MarketEntry) -> RawMarketData:
    for raw in raw_markets:
        if raw.market_id == market.platform_market_id:
            return _remap_raw_market(raw, market.id)
    raise RuntimeError(
        f"{market.platform} market {market.platform_market_id!r} "
        f"for configured id {market.id!r} was not returned by poll_markets"
    )


def _remap_raw_market(raw: RawMarketData, market_id: str) -> RawMarketData:
    return RawMarketData(
        market_id=market_id,
        platform=raw.platform,
        fetched_at=raw.fetched_at,
        payload=raw.payload,
    )


def _remap_trade(trade: RawTrade, market_id: str) -> RawTrade:
    return RawTrade(
        market_id=market_id,
        platform=trade.platform,
        timestamp=trade.timestamp,
        price=trade.price,
        size=trade.size,
        side=trade.side,
        counterparty=trade.counterparty,
    )


async def _run(config: RuntimeConfig) -> None:
    runtime = _build_runtime(config)
    since = datetime.now(tz=UTC) - timedelta(seconds=config.trade_lookback_seconds)
    async with aiohttp.ClientSession() as session:
        pollers = _build_pollers(session, runtime.markets)
        while True:
            snapshots, trades = await _fetch_cycle(pollers, runtime.markets, since)
            since = datetime.now(tz=UTC)
            features = _ingest_features(runtime, snapshots)
            contexts = await runtime.engine.run_cycle(
                snapshots=snapshots,
                features=features,
                recent_trades=trades,
                recent_book_events={},
                now=since,
            )
            for context in contexts:
                print(to_canonical_json(context).decode("utf-8"), flush=True)
            if config.once:
                _emit_once_summary(
                    _summarize_cycle(
                        storage=runtime.storage_label,
                        active_markets=len(runtime.markets),
                        platforms=_platform_counts(runtime.markets),
                        snapshots=snapshots,
                        trades=trades,
                        features=features,
                        signal_count=len(contexts),
                        feature_warmup_size=runtime.feature_config.warmup_size,
                    )
                )
                return
            await asyncio.sleep(config.poll_seconds)


def _ingest_features(
    runtime: EngineRuntime,
    snapshots: Sequence[MarketSnapshot],
) -> dict[str, FeatureVector]:
    features: dict[str, FeatureVector] = {}
    for snapshot in snapshots:
        feature = runtime.feature_pipeline.ingest(snapshot)
        if feature is not None:
            features[snapshot.market_id] = feature
    return features


def _summarize_cycle(
    *,
    storage: str,
    active_markets: int,
    platforms: tuple[str, ...],
    snapshots: Sequence[MarketSnapshot],
    trades: dict[str, list[RawTrade]],
    features: dict[str, FeatureVector],
    signal_count: int,
    feature_warmup_size: int,
) -> CycleSummary:
    return CycleSummary(
        storage=storage,
        active_markets=active_markets,
        platforms=platforms,
        snapshots=len(snapshots),
        trades=sum(len(market_trades) for market_trades in trades.values()),
        features=len(features),
        signals=signal_count,
        feature_warmup_size=feature_warmup_size,
    )


def _platform_counts(markets: Sequence[MarketEntry]) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for market in markets:
        counts[market.platform] = counts.get(market.platform, 0) + 1
    return tuple(f"{platform}:{count}" for platform, count in sorted(counts.items()))


def _emit_once_summary(summary: CycleSummary) -> None:
    lines = [
        f"augur run summary: status=ok mode=once storage={summary.storage}",
        "  markets: "
        f"active={summary.active_markets} "
        f"platforms={','.join(summary.platforms)} "
        f"snapshots={summary.snapshots}",
        f"  outputs: trades={summary.trades} features={summary.features} signals={summary.signals}",
    ]
    if summary.features < summary.active_markets:
        lines.append(
            "  note: feature buffers are still warming; "
            f"default warmup is {summary.feature_warmup_size} observations per market, "
            "and --once starts a fresh in-memory buffer"
        )
    print("\n".join(lines), file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        asyncio.run(_run(_parse_args(argv or sys.argv[1:])))
    except Exception as exc:
        print(f"run_engine failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
