"""SignalContext and RelatedMarketState — deterministic assembly envelope.

Schema authoritative in docs/contracts/schema-and-versioning.md
§SignalContext and §RelatedMarketState. Produced by the context
assembler; every field is verbatim from the platform or the curated
taxonomy / prompt library. The assembler never synthesizes prose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from augur_signals.models.enums import InterpretationMode
from augur_signals.models.signal import MarketSignal


class RelatedMarketState(BaseModel):
    """Snapshot of a related market at context-assembly time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_id: str
    question: str
    current_price: float
    delta_24h: float
    volume_24h: float
    relationship_type: Literal["positive", "inverse", "complex", "causal"]
    relationship_strength: float


class SignalContext(BaseModel):
    """Deterministic envelope wrapping a MarketSignal with platform metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: MarketSignal
    market_question: str
    resolution_criteria: str
    resolution_source: str
    closes_at: datetime
    related_markets: list[RelatedMarketState]
    investigation_prompts: list[str]
    interpretation_mode: InterpretationMode = InterpretationMode.DETERMINISTIC
    schema_version: Literal["1.0.0"] = "1.0.0"
