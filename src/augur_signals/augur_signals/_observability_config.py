"""Configuration model for observability backends.

Schema mirrors `config/observability.toml`. The "disabled" variants
are useful for unit tests and backtest runs where metric and trace
emission would pollute the signal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MetricsBody(BaseModel):
    """Prometheus exporter parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["disabled", "prometheus"] = "prometheus"
    # The "bind to all interfaces" default is intentional; the metrics
    # endpoint is reached from a sibling container (ServiceMonitor /
    # scraper) within the same Kubernetes pod network.
    prometheus_bind: str = "0.0.0.0"  # noqa: S104
    prometheus_port: int = Field(default=9090, gt=0, lt=65536)


class TracesBody(BaseModel):
    """OpenTelemetry OTLP exporter parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["disabled", "otlp"] = "otlp"
    otlp_endpoint: str = "http://otel-collector:4317"
    service_name: str = "augur"
    sampling_ratio: float = Field(default=0.1, ge=0.0, le=1.0)


class LogsBody(BaseModel):
    """Structured-log emitter parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "text"] = "json"


class ObservabilityConfig(BaseModel):
    """Top-level observability configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metrics: MetricsBody = Field(default_factory=MetricsBody)
    traces: TracesBody = Field(default_factory=TracesBody)
    logs: LogsBody = Field(default_factory=LogsBody)
