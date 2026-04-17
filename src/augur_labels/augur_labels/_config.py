"""Labeling-pipeline configuration models.

Schema mirrors the blocks in config/labeling.toml and matches the
defaults documented in phase-2 §11. Every field is validated at
startup via augur_signals._config.load_config; a missing required
value fails loudly rather than coercing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReutersSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    rate_limit_per_hour: int = Field(default=1000, gt=0)
    api_key_env: str = "REUTERS_API_KEY"


class BloombergSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    rate_limit_per_hour: int = Field(default=500, gt=0)
    client_id_env: str = "BLOOMBERG_CLIENT_ID"
    # Name of the env var that holds the secret, not the secret itself.
    client_secret_env: str = "BLOOMBERG_CLIENT_SECRET"  # noqa: S105


class ApSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    rate_limit_per_hour: int = Field(default=500, gt=0)
    api_key_env: str = "AP_API_KEY"


class FtSourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    rate_limit_per_hour: int = Field(default=200, gt=0)
    api_key_env: str = "FT_API_KEY"


class SourcesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reuters: ReutersSourceConfig = Field(default_factory=ReutersSourceConfig)
    bloomberg: BloombergSourceConfig = Field(default_factory=BloombergSourceConfig)
    ap: ApSourceConfig = Field(default_factory=ApSourceConfig)
    ft: FtSourceConfig = Field(default_factory=FtSourceConfig)


class WorkflowConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    double_label_window_days: int = Field(default=90, gt=0)
    timestamp_agreement_window_seconds: int = Field(default=60, gt=0)
    timestamp_hard_fail_seconds: int = Field(default=300, gt=0)
    market_jaccard_target: float = Field(default=0.85, ge=0.0, le=1.0)
    market_jaccard_hard_fail: float = Field(default=0.0, ge=0.0, le=1.0)
    category_kappa_target: float = Field(default=0.90, ge=-1.0, le=1.0)
    event_existence_kappa_target: float = Field(default=0.95, ge=-1.0, le=1.0)


class StorageConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    labels_root: str = "labels/newsworthy_events"
    file_lock_timeout_seconds: int = Field(default=30, gt=0)


class JoinConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lead_window_hours: int = Field(default=24, gt=0)
    true_negative_window_hours: int = Field(default=24, gt=0)


class LabelingConfig(BaseModel):
    """Top-level labeling configuration loaded from config/labeling.toml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    join: JoinConfig = Field(default_factory=JoinConfig)
