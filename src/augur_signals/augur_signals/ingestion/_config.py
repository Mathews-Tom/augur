"""Configuration models for ingestion and adaptive polling.

Schema mirrors docs/architecture/adaptive-polling-spec.md §Configuration
verbatim. Loaded from config/polling.toml at engine startup via
augur_signals._config.load_config.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HysteresisBands(BaseModel):
    """Promotion and demotion thresholds on volume_ratio_1h."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hot_promote: float = 2.2
    hot_demote: float = 1.8
    warm_promote: float = 1.5
    warm_demote: float = 1.3
    cool_promote: float = 1.1
    cool_demote: float = 0.9


class PlatformCaps(BaseModel):
    """Per-platform request-rate budgets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    polymarket_per_min: int = Field(default=600, gt=0)
    kalshi_per_min: int = Field(default=1000, gt=0)
    budget_safety_pct: float = Field(default=0.7, gt=0.0, le=1.0)


class BackoffSettings(BaseModel):
    """Retry backoff for transient failures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_s: float = Field(default=1.0, gt=0.0)
    max_s: float = Field(default=60.0, gt=0.0)
    max_retries: int = Field(default=5, gt=0)
    demote_after_consecutive_failures: int = 10
    remove_after_consecutive_failures: int = 50


class PollingBody(BaseModel):
    """Tier intervals, hysteresis bands, platform caps, and backoff."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hot_interval_s: int = 15
    warm_interval_s: int = 30
    cool_interval_s: int = 60
    cold_interval_s: int = 300
    hysteresis: HysteresisBands = Field(default_factory=HysteresisBands)
    platform_caps: PlatformCaps = Field(default_factory=PlatformCaps)
    backoff: BackoffSettings = Field(default_factory=BackoffSettings)


class PollingConfig(BaseModel):
    """Top-level polling configuration loaded from config/polling.toml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    polling: PollingBody
