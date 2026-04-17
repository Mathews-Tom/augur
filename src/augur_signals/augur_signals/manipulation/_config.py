"""Manipulation-detection configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ManipulationConfig(BaseModel):
    """Thresholds mirroring docs/methodology/manipulation-taxonomy.md §Thresholds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    herfindahl_threshold: float = Field(default=0.4, gt=0.0, le=1.0)
    size_vs_depth_threshold: float = Field(default=0.4, gt=0.0, le=1.0)
    cancel_replace_window_seconds: int = Field(default=60, gt=0)
    cancel_replace_min_count: int = Field(default=20, gt=0)
    thin_book_min_depth: float = Field(default=5_000.0, ge=0.0)
    pre_resolution_window_seconds: int = Field(default=21_600, gt=0)
