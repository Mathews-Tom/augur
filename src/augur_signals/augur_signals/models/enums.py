"""Closed enums for every consumer-facing string field.

Authoritative catalogue in docs/contracts/schema-and-versioning.md
§Closed Enums. Adding a member requires a schema-version bump per the
versioning policy in that document.
"""

from __future__ import annotations

from enum import StrEnum


class SignalType(StrEnum):
    """Detector signal types produced by the extraction layer."""

    PRICE_VELOCITY = "price_velocity"
    VOLUME_SPIKE = "volume_spike"
    BOOK_IMBALANCE = "book_imbalance"
    CROSS_MARKET_DIVERGENCE = "cross_market_divergence"
    REGIME_SHIFT = "regime_shift"


class ManipulationFlag(StrEnum):
    """Signature matches attached to signals by the manipulation detector."""

    SINGLE_COUNTERPARTY_CONCENTRATION = "single_counterparty_concentration"
    SIZE_VS_DEPTH_OUTLIER = "size_vs_depth_outlier"
    CANCEL_REPLACE_BURST = "cancel_replace_burst"
    THIN_BOOK_DURING_MOVE = "thin_book_during_move"
    PRE_RESOLUTION_WINDOW = "pre_resolution_window"


class ConsumerType(StrEnum):
    """Registered consumers of the brief feed per docs/contracts/consumer-registry.md."""

    MACRO_RESEARCH_AGENT = "macro_research_agent"
    GEOPOLITICAL_RESEARCH_AGENT = "geopolitical_research_agent"
    CRYPTO_RESEARCH_AGENT = "crypto_research_agent"
    FINANCIAL_NEWS_DESK = "financial_news_desk"
    REGULATORY_NEWS_DESK = "regulatory_news_desk"
    DASHBOARD = "dashboard"


class InterpretationMode(StrEnum):
    """How a SignalContext or IntelligenceBrief was produced."""

    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
