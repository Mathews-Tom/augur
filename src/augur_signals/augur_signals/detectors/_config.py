"""Per-detector configuration models.

Schema mirrors config/detectors.toml. Each detector block is
authoritative in docs/methodology/calibration-methodology.md for its
parameter semantics; the Pydantic models here only validate shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PriceVelocityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hazard_rate: float = Field(default=0.004, gt=0.0)
    alpha_prior: float = Field(default=1.0, gt=0.0)
    beta_prior: float = Field(default=1.0, gt=0.0)
    run_length_cap: int = Field(default=1000, gt=0)
    fire_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    resolution_exclusion_seconds: int = Field(default=21600, gt=0)
    cooldown_seconds: int = Field(default=900, ge=0)


class VolumeSpikeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ewma_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    min_absolute_volume: float = Field(default=10_000.0, ge=0.0)
    minimum_z: float = Field(default=1.65, ge=0.0)
    target_fdr_q: float = Field(default=0.05, gt=0.0, lt=1.0)
    resolution_exclusion_seconds: int = 21_600


class BookImbalanceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    depth_levels: int = Field(default=5, gt=0)
    bullish_threshold: float = Field(default=0.72, gt=0.5, le=1.0)
    bearish_threshold: float = Field(default=0.28, ge=0.0, lt=0.5)
    persistence_snapshots: int = Field(default=3, gt=0)
    minimum_total_depth: float = Field(default=5_000.0, ge=0.0)
    resolution_exclusion_seconds: int = 21_600


class CrossMarketConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window_seconds: int = Field(default=14_400, gt=0)
    min_historical_correlation: float = Field(default=0.6, ge=0.0, le=1.0)
    activity_floor: float = Field(default=1.0, ge=0.0)
    target_fdr_q: float = Field(default=0.05, gt=0.0, lt=1.0)
    resolution_exclusion_seconds: int = 21_600


class RegimeShiftConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_alpha: float = Field(default=0.02, gt=0.0, lt=1.0)
    k_multiplier: float = Field(default=0.5, gt=0.0)
    h_multiplier: float = Field(default=4.0, gt=0.0)
    dormancy_minimum_seconds: int = Field(default=21_600, gt=0)
    adaptive_cooldown_factor: float = Field(default=2.0, gt=0.0)
    resolution_exclusion_seconds: int = 21_600


class DetectorsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    price_velocity: PriceVelocityConfig = Field(default_factory=PriceVelocityConfig)
    volume_spike: VolumeSpikeConfig = Field(default_factory=VolumeSpikeConfig)
    book_imbalance: BookImbalanceConfig = Field(default_factory=BookImbalanceConfig)
    cross_market: CrossMarketConfig = Field(default_factory=CrossMarketConfig)
    regime_shift: RegimeShiftConfig = Field(default_factory=RegimeShiftConfig)
