"""Feature-pipeline configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeaturePipelineConfig(BaseModel):
    """Buffer size and EWMA parameters for the feature pipeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    buffer_size: int = Field(default=500, gt=0)
    warmup_size: int = Field(default=50, gt=0)
    ewma_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    max_polling_interval_seconds: int = 300
