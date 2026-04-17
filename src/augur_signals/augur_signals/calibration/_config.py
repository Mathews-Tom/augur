"""Calibration layer configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CalibrationConfig(BaseModel):
    """Thresholds and sample-size floors for the calibration layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_fdr_q: float = Field(default=0.05, gt=0.0, lt=1.0)
    sample_size_floor: int = Field(default=100, gt=0)
    psi_trigger_threshold: float = Field(default=0.2, gt=0.0)
    ks_p_value_threshold: float = Field(default=0.01, gt=0.0, lt=1.0)
