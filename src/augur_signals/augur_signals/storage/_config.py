"""Configuration model for storage backend selection.

Schema mirrors `config/storage.toml`. The Phase 1-4 monolith reads
`backend.kind == "duckdb"`; Phase 5 cutover flips it to
`"timescaledb"`. See `.docs/phase-5-scaling.md §5` for the cutover
procedure and rollback constraints.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BackendBody(BaseModel):
    """Which backing store the engine opens at startup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["duckdb", "timescaledb"]
    duckdb_path: str = "data/augur.duckdb"
    timescale_url_env: str = "AUGUR_TIMESCALE_URL"


class ConnectionBody(BaseModel):
    """Connection-pool shape used by the TimescaleDB adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pool_size: int = Field(default=20, gt=0)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout_seconds: int = Field(default=30, gt=0)


class MigrationBody(BaseModel):
    """Parquet-to-TimescaleDB migration settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parquet_archive_root: str = "labels/snapshots_archive"
    dual_write_lag_alert_seconds: int = Field(default=10, gt=0)


class HypertableBody(BaseModel):
    """Chunk intervals for each hypertable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_chunk_interval_days: int = Field(default=1, gt=0)
    feature_chunk_interval_days: int = Field(default=1, gt=0)
    signal_chunk_interval_days: int = Field(default=7, gt=0)


class RetentionBody(BaseModel):
    """Retention policies in days; 0 disables the policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_retention_days: int = Field(default=0, ge=0)
    feature_retention_days: int = Field(default=30, ge=0)
    signal_retention_days: int = Field(default=0, ge=0)


class CompressionBody(BaseModel):
    """Compression policies in days; 0 disables compression."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_compress_after_days: int = Field(default=7, ge=0)
    feature_compress_after_days: int = Field(default=7, ge=0)
    signal_compress_after_days: int = Field(default=30, ge=0)


class StorageConfig(BaseModel):
    """Top-level storage configuration loaded from `config/storage.toml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: BackendBody
    connection: ConnectionBody = Field(default_factory=ConnectionBody)
    migration: MigrationBody = Field(default_factory=MigrationBody)
    hypertable: HypertableBody = Field(default_factory=HypertableBody)
    retention: RetentionBody = Field(default_factory=RetentionBody)
    compression: CompressionBody = Field(default_factory=CompressionBody)
