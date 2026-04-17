"""FeatureVector — rolling-window feature set per market per tick.

Schema authoritative in docs/contracts/schema-and-versioning.md
§FeatureVector. Produced by the feature pipeline from the snapshot
buffer; consumed by the detectors. Computation is idempotent — same
buffer in, same vector out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FeatureVector(BaseModel):
    """Per-market features at a single computation tick."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_id: str
    computed_at: datetime
    price_momentum_5m: float
    price_momentum_15m: float
    price_momentum_1h: float
    price_momentum_4h: float
    volatility_5m: float
    volatility_15m: float
    volatility_1h: float
    volatility_4h: float
    volume_ratio_5m: float
    volume_ratio_1h: float
    bid_ask_ratio: float | None
    spread_pct: float | None
    schema_version: Literal["1.0.0"] = "1.0.0"
