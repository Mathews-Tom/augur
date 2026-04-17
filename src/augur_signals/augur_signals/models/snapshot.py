"""MarketSnapshot — normalized observation of a market at a single tick.

Schema authoritative in docs/contracts/schema-and-versioning.md
§MarketSnapshot. Produced by the normalizer from platform-specific
raw responses; consumed by the feature pipeline and persisted to the
snapshots table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MarketSnapshot(BaseModel):
    """A normalized, platform-agnostic market-state observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_id: str
    platform: Literal["polymarket", "kalshi"]
    timestamp: datetime
    last_price: Annotated[float, Field(ge=0.0, le=1.0)]
    bid: float | None
    ask: float | None
    spread: float | None
    volume_24h: Annotated[float, Field(ge=0.0)]
    liquidity: Annotated[float, Field(ge=0.0)]
    question: str
    resolution_source: str | None
    resolution_criteria: str | None
    closes_at: datetime | None
    raw_json: dict[str, Any]
    schema_version: Literal["1.0.0"] = "1.0.0"
