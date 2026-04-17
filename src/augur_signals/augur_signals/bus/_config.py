"""Configuration model for the message bus.

Schema mirrors `config/bus.toml`. The default backend is "memory" —
the in-process bus used by the monolith. Phase 5 flips the field to
"nats" or "redis" after the operator chooses the cluster topology;
see `.docs/phase-5-scaling.md §4` for the decision matrix.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BackendBody(BaseModel):
    """Bus backend selector with defaults tuned for the monolith."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["memory", "nats", "redis"]
    capacity: int = Field(default=256, gt=0)


class NATSBody(BaseModel):
    """NATS JetStream connection parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    servers: list[str] = Field(default_factory=lambda: ["nats://localhost:4222"])
    credentials_file_env: str = "NATS_CREDENTIALS_FILE"
    stream_name: str = "augur"
    replication_factor: int = Field(default=3, gt=0)
    subject_prefix: str = "augur"


class RedisBody(BaseModel):
    """Redis Streams connection parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url_env: str = "REDIS_URL"
    stream_max_length: int = Field(default=100_000, gt=0)
    consumer_group_prefix: str = "augur"
    block_ms: int = Field(default=1000, gt=0)


class LockBody(BaseModel):
    """Distributed-lock parameters used by active-passive singletons."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ttl_seconds: int = Field(default=30, gt=0)
    renew_interval_seconds: int = Field(default=10, gt=0)


class BusConfig(BaseModel):
    """Top-level bus configuration loaded from `config/bus.toml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: BackendBody
    nats: NATSBody = Field(default_factory=NATSBody)
    redis: RedisBody = Field(default_factory=RedisBody)
    lock: LockBody = Field(default_factory=LockBody)
