"""Configuration models for deterministic formatters.

Mirrors config/formatters.toml block-for-block. Loaded at engine
startup via augur_signals._config.load_config; a missing required
value or malformed block fails loudly rather than coercing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JsonConfig(BaseModel):
    """Canonical JSON formatter parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    float_decimals: int = Field(default=6, ge=0, le=18)
    timestamp_format: Literal["iso_z"] = "iso_z"


class MarkdownConfig(BaseModel):
    """Jinja2 rendering parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    template_dir: str = "src/augur_format/augur_format/deterministic/templates"
    trim_blocks: bool = True
    lstrip_blocks: bool = True


class WebhookConfig(BaseModel):
    """Webhook delivery retry and timeout settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_retry_delay_seconds: float = Field(default=1.0, gt=0.0)
    max_retry_delay_seconds: float = Field(default=60.0, gt=0.0)
    max_retries: int = Field(default=5, gt=0)
    delivery_timeout_seconds: float = Field(default=10.0, gt=0.0)


class WebSocketConfig(BaseModel):
    """WebSocket transport bind, heartbeat, and per-connection buffer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bind: str = "0.0.0.0"  # noqa: S104 — documented default bind for the WS server
    port: int = Field(default=8765, gt=0, le=65_535)
    heartbeat_interval_seconds: int = Field(default=30, gt=0)
    heartbeat_timeout_seconds: int = Field(default=90, gt=0)
    per_connection_buffer: int = Field(default=64, gt=0)


class FormatterConfig(BaseModel):
    """Top-level formatter configuration loaded from config/formatters.toml."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    # Field aliased so the TOML block is [json] per the documented
    # schema, while the Python attribute is `canonical_json` to avoid
    # shadowing BaseModel.json.
    canonical_json: JsonConfig = Field(default_factory=JsonConfig, alias="json")
    markdown: MarkdownConfig = Field(default_factory=MarkdownConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
