"""Consumer registry loader.

Reads ``config/consumers.toml`` (seeded in the workspace bootstrap)
and exposes the per-category consumer routing plus per-consumer
transport configuration. The router consumes the registry to decide
which consumers should receive a given signal.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from augur_signals.models import ConsumerType


@dataclass(frozen=True, slots=True)
class CategoryRouting:
    """Default consumers for a market category."""

    category: str
    consumers: tuple[ConsumerType, ...]


class ConsumerRegistry:
    """Read-only registry loaded from config/consumers.toml."""

    def __init__(self, routing: dict[str, tuple[ConsumerType, ...]]) -> None:
        self._routing = dict(routing)

    def consumers_for_category(self, category: str) -> tuple[ConsumerType, ...]:
        """Return the default consumers for *category*.

        Unknown categories fall through to ``default`` — matching the
        Routing Table in docs/contracts/consumer-registry.md.
        """
        if category in self._routing:
            return self._routing[category]
        return self._routing.get("default", (ConsumerType.DASHBOARD,))

    def known_categories(self) -> frozenset[str]:
        return frozenset(self._routing.keys())

    @classmethod
    def from_toml(cls, path: Path) -> ConsumerRegistry:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        categories_raw = raw.get("categories", {})
        routing: dict[str, tuple[ConsumerType, ...]] = {}
        for category, entry in categories_raw.items():
            consumers = tuple(ConsumerType(value) for value in entry.get("consumers", []))
            routing[category] = consumers
        if "default" not in routing:
            routing["default"] = (ConsumerType.DASHBOARD,)
        return cls(routing)


@dataclass(frozen=True, slots=True)
class CategoryCoverage:
    """One entry of the coverage report."""

    category: str
    consumer_count: int
    has_default_fallback: bool
    consumers: list[str] = field(default_factory=list)
