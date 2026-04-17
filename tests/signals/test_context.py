"""Tests for taxonomy, prompt library, related resolver, and context assembler."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from augur_signals.context.assembler import ContextAssembler, MissingMetadataError
from augur_signals.context.investigation_prompts import InvestigationPromptLibrary
from augur_signals.context.related import RelatedMarketResolver
from augur_signals.context.taxonomy import MarketTaxonomy, TaxonomyEdge
from augur_signals.models import (
    InterpretationMode,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)
from augur_signals.storage.duckdb_store import DuckDBStore


def _snapshot(
    market_id: str, offset: int = 0, price: float = 0.5, question: str = "Q"
) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC) + timedelta(seconds=offset),
        last_price=price,
        bid=max(0.0, price - 0.01),
        ask=min(1.0, price + 0.01),
        spread=0.02,
        volume_24h=200_000.0,
        liquidity=5_000.0,
        question=question,
        resolution_source="Source",
        resolution_criteria="Criteria",
        closes_at=datetime(2026, 6, 15, tzinfo=UTC),
        raw_json={"k": 1},
    )


def _signal(market_id: str = "a") -> MarketSignal:
    return MarketSignal(
        signal_id=new_signal_id(),
        market_id=market_id,
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.8,
        direction=1,
        confidence=0.75,
        fdr_adjusted=False,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        raw_features={"calibration_provenance": "d@identity_v0"},
    )


@pytest.mark.unit
def test_taxonomy_edges_are_bidirectional() -> None:
    tx = MarketTaxonomy([TaxonomyEdge("a", "b", "inverse", 0.9)])
    assert {e.market_b for e in tx.edges_for("a")} == {"b"}
    assert {e.market_b for e in tx.edges_for("b")} == {"a"}


@pytest.mark.unit
def test_taxonomy_cluster_filters_by_type() -> None:
    tx = MarketTaxonomy(
        [
            TaxonomyEdge("a", "b", "positive", 0.8),
            TaxonomyEdge("a", "c", "complex", 0.5),
        ]
    )
    assert tx.cluster_for("a") == {"b"}


@pytest.mark.unit
def test_prompt_library_lookup_and_coverage() -> None:
    lib = InvestigationPromptLibrary(
        [(SignalType.PRICE_VELOCITY, "monetary_policy", ["Check FOMC"])]
    )
    assert lib.lookup(SignalType.PRICE_VELOCITY, "monetary_policy") == ["Check FOMC"]
    assert lib.lookup(SignalType.VOLUME_SPIKE, "monetary_policy") == []
    report = lib.coverage_report(["monetary_policy", "geopolitics"])
    # 5 signal types * 2 categories = 10 cells, 1 filled => 9 missing.
    assert report.total_categories == 10
    assert report.covered == 1
    assert len(report.missing) == 9


@pytest.mark.unit
def test_prompt_library_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "prompts.toml"
    path.write_text(
        """
[[prompts]]
signal_type = "price_velocity"
market_category = "monetary_policy"
prompts = ["Check FOMC calendar"]
""",
        encoding="utf-8",
    )
    lib = InvestigationPromptLibrary.from_toml(path)
    assert lib.lookup(SignalType.PRICE_VELOCITY, "monetary_policy") == ["Check FOMC calendar"]


@pytest.mark.unit
def test_taxonomy_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "markets.toml"
    path.write_text(
        """
[[relationships]]
market_a = "a"
market_b = "b"
type = "inverse"
strength = 0.9
source = "manual"
""",
        encoding="utf-8",
    )
    # Verify the file parses — validation otherwise happens in MarketTaxonomy.
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    assert raw["relationships"][0]["market_a"] == "a"
    tx = (
        MarketTaxonomy.from_taxonomy_dict(raw)
        if hasattr(MarketTaxonomy, "from_taxonomy_dict")
        else MarketTaxonomy.from_toml(path)
    )
    assert len(tx.edges_for("a")) == 1


@pytest.mark.unit
def test_context_assembler_deterministic(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "a.duckdb")
    store.initialize()
    store.insert_snapshot(_snapshot("a", question="Will X?"))
    store.insert_snapshot(_snapshot("b", price=0.3, question="Will Y?"))
    taxonomy = MarketTaxonomy([TaxonomyEdge("a", "b", "inverse", 0.9)])
    resolver = RelatedMarketResolver(taxonomy, store)
    library = InvestigationPromptLibrary(
        [(SignalType.PRICE_VELOCITY, "monetary_policy", ["Check FOMC"])]
    )
    assembler = ContextAssembler(store, resolver, library, {"a": "monetary_policy"})
    signal = _signal()
    first = assembler.assemble(signal)
    second = assembler.assemble(signal)
    assert first.model_dump_json() == second.model_dump_json()
    assert first.interpretation_mode == InterpretationMode.DETERMINISTIC
    assert first.market_question == "Will X?"
    assert first.investigation_prompts == ["Check FOMC"]
    assert len(first.related_markets) == 1
    store.close()


@pytest.mark.unit
def test_context_assembler_raises_on_missing_metadata(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "b.duckdb")
    store.initialize()
    taxonomy = MarketTaxonomy([])
    resolver = RelatedMarketResolver(taxonomy, store)
    library = InvestigationPromptLibrary([])
    assembler = ContextAssembler(store, resolver, library)
    with pytest.raises(MissingMetadataError):
        assembler.assemble(_signal())
    store.close()
