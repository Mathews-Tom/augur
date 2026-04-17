"""Tests for consumer registry and the signal router."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from augur_format.routing.consumer_registry import ConsumerRegistry
from augur_format.routing.router import SignalRouter
from augur_signals.models import (
    ConsumerType,
    InterpretationMode,
    MarketSignal,
    SignalContext,
    SignalType,
    new_signal_id,
)


def _context(
    market_id: str = "kalshi_fed",
    interpretation_mode: InterpretationMode = InterpretationMode.DETERMINISTIC,
) -> SignalContext:
    signal = MarketSignal(
        signal_id=new_signal_id(),
        market_id=market_id,
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.8,
        direction=1,
        confidence=0.7,
        fdr_adjusted=True,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        raw_features={"calibration_provenance": "d@identity_v0"},
    )
    return SignalContext(
        signal=signal,
        market_question="q",
        resolution_criteria="c",
        resolution_source="s",
        closes_at=datetime(2026, 6, 15, tzinfo=UTC),
        related_markets=[],
        investigation_prompts=[],
        interpretation_mode=interpretation_mode,
    )


@pytest.mark.unit
def test_registry_from_toml_reads_routing() -> None:
    registry = ConsumerRegistry.from_toml(Path("config/consumers.toml"))
    consumers = registry.consumers_for_category("monetary_policy")
    assert ConsumerType.MACRO_RESEARCH_AGENT in consumers
    assert ConsumerType.FINANCIAL_NEWS_DESK in consumers
    assert ConsumerType.DASHBOARD in consumers


@pytest.mark.unit
def test_registry_falls_through_to_default_on_unknown_category() -> None:
    registry = ConsumerRegistry.from_toml(Path("config/consumers.toml"))
    consumers = registry.consumers_for_category("not-a-real-category")
    assert consumers == (ConsumerType.DASHBOARD,)


@pytest.mark.unit
def test_router_returns_default_consumers_for_unregistered_market() -> None:
    registry = ConsumerRegistry.from_toml(Path("config/consumers.toml"))
    router = SignalRouter(registry)
    decision = router.route(_context())
    assert ConsumerType.DASHBOARD in decision.consumers


@pytest.mark.unit
def test_router_applies_market_category() -> None:
    registry = ConsumerRegistry.from_toml(Path("config/consumers.toml"))
    router = SignalRouter(registry, market_categories={"kalshi_fed": "monetary_policy"})
    decision = router.route(_context())
    assert ConsumerType.MACRO_RESEARCH_AGENT in decision.consumers


@pytest.mark.unit
def test_router_suppresses_non_llm_consumers_on_llm_assisted_context() -> None:
    registry = ConsumerRegistry.from_toml(Path("config/consumers.toml"))
    router = SignalRouter(registry, market_categories={"kalshi_fed": "monetary_policy"})
    decision = router.route(_context(interpretation_mode=InterpretationMode.LLM_ASSISTED))
    assert ConsumerType.DASHBOARD in decision.consumers
    assert ConsumerType.MACRO_RESEARCH_AGENT in decision.suppressed
    assert ConsumerType.MACRO_RESEARCH_AGENT not in decision.consumers


@pytest.mark.unit
def test_router_register_market_category_is_idempotent() -> None:
    registry = ConsumerRegistry.from_toml(Path("config/consumers.toml"))
    router = SignalRouter(registry)
    router.register_market_category("kalshi_fed", "monetary_policy")
    router.register_market_category("kalshi_fed", "monetary_policy")
    decision = router.route(_context())
    assert ConsumerType.MACRO_RESEARCH_AGENT in decision.consumers
