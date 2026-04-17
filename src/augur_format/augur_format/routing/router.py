"""Signal router — decides which consumers receive each SignalContext.

The router composes the category-to-consumers mapping from the
ConsumerRegistry with per-consumer suppression policy (for example,
whether a consumer accepts LLM-assisted briefs). In Phase 3 every
brief emitted is deterministic, so the suppression flag is unused
today; it becomes load-bearing once the gated secondary formatter
produces llm_assisted briefs.
"""

from __future__ import annotations

from dataclasses import dataclass

from augur_format.routing.consumer_registry import ConsumerRegistry
from augur_signals.models import (
    ConsumerType,
    InterpretationMode,
    SignalContext,
)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The set of consumers receiving a given context plus reasons."""

    consumers: tuple[ConsumerType, ...]
    suppressed: tuple[ConsumerType, ...] = ()


class SignalRouter:
    """Route SignalContext into consumer sets."""

    def __init__(
        self,
        registry: ConsumerRegistry,
        market_categories: dict[str, str] | None = None,
        llm_assisted_consumers: frozenset[ConsumerType] | None = None,
    ) -> None:
        self._registry = registry
        self._market_categories = dict(market_categories or {})
        # Consumers that opt in to llm_assisted briefs. Dashboard is
        # the documented default from consumer-registry.md §Why Each
        # Consumer Exists.
        self._llm_assisted = llm_assisted_consumers or frozenset({ConsumerType.DASHBOARD})

    def register_market_category(self, market_id: str, category: str) -> None:
        self._market_categories[market_id] = category

    def route(self, context: SignalContext) -> RoutingDecision:
        """Return the consumer set for *context*.

        Consumers whose subscription excludes the context's
        interpretation_mode are reported under ``suppressed`` so
        operational metrics can count the drops.
        """
        category = self._market_categories.get(context.signal.market_id, "default")
        candidates = self._registry.consumers_for_category(category)
        if context.interpretation_mode == InterpretationMode.LLM_ASSISTED:
            allowed = tuple(c for c in candidates if c in self._llm_assisted)
            suppressed = tuple(c for c in candidates if c not in self._llm_assisted)
            return RoutingDecision(consumers=allowed, suppressed=suppressed)
        return RoutingDecision(consumers=candidates)
