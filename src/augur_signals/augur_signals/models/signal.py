"""MarketSignal — the canonical typed event emitted by the extraction layer.

Schema authoritative in docs/contracts/schema-and-versioning.md
§MarketSignal. Every signal carries calibrated confidence, FDR-adjusted
threshold status, and a non-empty calibration provenance stamp. The
model_validator enforces the provenance invariant so no uncalibrated
signal escapes the producer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from augur_signals.models.enums import ManipulationFlag, SignalType


class MarketSignal(BaseModel):
    """Canonical structured event emitted by the extraction layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str
    market_id: str
    platform: Literal["polymarket", "kalshi"]
    signal_type: SignalType
    magnitude: Annotated[float, Field(ge=0.0, le=1.0)]
    direction: Literal[-1, 0, 1]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    fdr_adjusted: bool
    detected_at: datetime
    window_seconds: Annotated[int, Field(gt=0)]
    liquidity_tier: Literal["high", "mid", "low"]
    manipulation_flags: list[ManipulationFlag] = Field(default_factory=list)
    related_market_ids: list[str] = Field(default_factory=list)
    raw_features: dict[str, float | str]
    schema_version: Literal["1.0.0"] = "1.0.0"

    @model_validator(mode="after")
    def _calibration_provenance_required(self) -> MarketSignal:
        provenance = self.raw_features.get("calibration_provenance")
        if not isinstance(provenance, str) or not provenance:
            raise ValueError(
                "MarketSignal.raw_features['calibration_provenance'] "
                "must be a non-empty string; the calibration layer "
                "stamps this field before the signal leaves the producer."
            )
        return self
