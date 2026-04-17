"""Shared bootstrap helpers for worker `__main__` modules.

Every worker entrypoint follows the same startup sequence:

1. Load `BusConfig`, `StorageConfig`, `ObservabilityConfig` from the
   TOML files under `$AUGUR_CONFIG_DIR` (default `config/`).
2. Activate the observability backend and open the Prometheus
   scrape listener.
3. Build the `EventBus` and (if the worker needs it) the storage
   adapter.

This module centralizes that plumbing so per-worker modules stay
focused on the transform. Every helper fails loud on missing or
inconsistent config — no silent fallbacks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from augur_signals._config import load_config
from augur_signals._observability import configure_observability, start_metrics_server
from augur_signals._observability_config import ObservabilityConfig
from augur_signals.bus._config import BusConfig
from augur_signals.bus.base import EventBus
from augur_signals.bus.factory import make_event_bus
from augur_signals.bus.memory import InProcessAsyncBus
from augur_signals.storage._config import StorageConfig


@dataclass(frozen=True, slots=True)
class RuntimeConfigs:
    """Triple of configs every worker loads at startup."""

    bus: BusConfig
    storage: StorageConfig
    observability: ObservabilityConfig


def config_dir() -> Path:
    """Resolve the active config directory from `AUGUR_CONFIG_DIR`."""
    return Path(os.environ.get("AUGUR_CONFIG_DIR", "config")).resolve()


def load_runtime_configs(config_dir_override: Path | None = None) -> RuntimeConfigs:
    """Load the three TOML configs every worker depends on."""
    root = config_dir_override if config_dir_override is not None else config_dir()
    return RuntimeConfigs(
        bus=load_config(root / "bus.toml", BusConfig),
        storage=load_config(root / "storage.toml", StorageConfig),
        observability=load_config(root / "observability.toml", ObservabilityConfig),
    )


def activate_observability(config: ObservabilityConfig) -> None:
    """Configure the observability backend and open the metrics port."""
    configure_observability(config)
    start_metrics_server(config)


def build_event_bus(config: BusConfig) -> EventBus:
    """Return an `EventBus` for *config*.

    The memory backend is served by the monolith's `InProcessAsyncBus`
    wrapper — not the byte-level `EventBus` factory. For a worker to
    use the memory backend it must wrap the `InProcessAsyncBus` with a
    subject-aware shim, which is out of scope for this bootstrap. The
    factory call covers `nats` and `redis`; `memory` raises a clear
    error pointing to the monolith engine.
    """
    if config.backend.kind == "memory":
        raise RuntimeError(
            "Worker bootstrap does not serve the 'memory' bus backend. "
            "Set bus.backend.kind to 'nats' or 'redis' in bus.toml, or "
            "run the monolith engine which uses InProcessAsyncBus directly."
        )
    return make_event_bus(config)


def resolve_replica_id() -> str:
    """Read the replica's stable identifier from the environment.

    Kubernetes pods set `POD_NAME` via the Downward API; plain-container
    deployments supply `AUGUR_REPLICA_ID`. Missing both is a fatal
    configuration error because per-replica metric labels and
    distributed-lock holder ids depend on the value.
    """
    replica = os.environ.get("AUGUR_REPLICA_ID") or os.environ.get("POD_NAME")
    if not replica:
        raise RuntimeError(
            "Replica id is unset. Populate AUGUR_REPLICA_ID or POD_NAME in the worker environment."
        )
    return replica


def parse_shard_arg(shard: str) -> tuple[int, int]:
    """Parse a `"index/count"` shard argument to `(index, count)`.

    Raises:
        ValueError: The argument is malformed or uses a non-positive
            count, or the index is out of range.
    """
    parts = shard.split("/")
    if len(parts) != 2:
        raise ValueError(f"Expected 'index/count' shard arg, got {shard!r}")
    try:
        index = int(parts[0])
        count = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"Shard components must be integers: {shard!r}") from exc
    if count <= 0:
        raise ValueError(f"Shard count must be positive, got {count}")
    if index < 0 or index >= count:
        raise ValueError(f"Shard index {index} out of range for count {count}")
    return index, count


# Re-export so callers do not need to reach into bus.memory directly.
__all__ = [
    "InProcessAsyncBus",
    "RuntimeConfigs",
    "activate_observability",
    "build_event_bus",
    "config_dir",
    "load_runtime_configs",
    "parse_shard_arg",
    "resolve_replica_id",
]
