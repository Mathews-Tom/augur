"""Curated market-taxonomy loader.

Reads edges from ``config/markets.toml``'s ``[[relationships]]`` blocks
or a dedicated taxonomy file. Only ``manual`` edges are supported in
this workstream; embedding-derived edges land alongside the LLM
formatter work.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class TaxonomyEdge:
    """One pair of related markets with a typed relationship."""

    market_a: str
    market_b: str
    relationship_type: Literal["positive", "inverse", "complex", "causal"]
    strength: float
    source: Literal["manual", "embedding"] = "manual"


class MarketTaxonomy:
    """Holds the curated edge set and answers relationship queries."""

    def __init__(self, edges: Iterable[TaxonomyEdge]) -> None:
        self._edges: dict[str, list[TaxonomyEdge]] = {}
        for edge in edges:
            self._edges.setdefault(edge.market_a, []).append(edge)
            flipped = TaxonomyEdge(
                market_a=edge.market_b,
                market_b=edge.market_a,
                relationship_type=edge.relationship_type,
                strength=edge.strength,
                source=edge.source,
            )
            self._edges.setdefault(edge.market_b, []).append(flipped)

    def edges_for(self, market_id: str) -> list[TaxonomyEdge]:
        return list(self._edges.get(market_id, []))

    def cluster_for(self, market_id: str, types: set[str] | None = None) -> set[str]:
        allowed = types or {"positive", "inverse", "causal"}
        return {
            edge.market_b for edge in self.edges_for(market_id) if edge.relationship_type in allowed
        }

    @classmethod
    def from_toml(cls, path: Path) -> MarketTaxonomy:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        edges_raw = raw.get("relationships", [])
        edges = [
            TaxonomyEdge(
                market_a=str(item["market_a"]),
                market_b=str(item["market_b"]),
                relationship_type=item["type"],
                strength=float(item.get("strength", 1.0)),
                source=item.get("source", "manual"),
            )
            for item in edges_raw
        ]
        return cls(edges)
