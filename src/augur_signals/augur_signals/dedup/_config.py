"""Configuration models for deduplication and storm handling."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BusSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    queue_capacity: int = Field(default=256, gt=0)
    per_consumer_buffer: int = Field(default=64, gt=0)
    context_assembler_concurrency: int = Field(default=4, gt=0)
    llm_formatter_concurrency: int = Field(default=1, gt=0)


class StormSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_signal_rate_per_sec: float = 20.0
    trigger_signal_rate_window_sec: int = 30
    trigger_queue_depth_pct: float = 0.75
    trigger_queue_depth_window_sec: int = 10
    recovery_signal_rate_per_sec: float = 5.0
    recovery_signal_rate_window_sec: int = 60
    recovery_queue_depth_pct: float = 0.25
    recovery_queue_depth_window_sec: int = 30


class DedupBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fingerprint_bucket_seconds: int = 30
    cluster_window_seconds: int = 90
    cluster_relationship_types: list[str] = Field(
        default_factory=lambda: ["positive", "inverse", "causal"]
    )
    bus: BusSettings = Field(default_factory=BusSettings)
    storm: StormSettings = Field(default_factory=StormSettings)


class DedupConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dedup: DedupBody
