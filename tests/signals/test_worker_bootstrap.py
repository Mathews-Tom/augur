"""Tests for the worker bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from augur_signals.bus._config import BackendBody, BusConfig
from augur_signals.bus.nats import NATSBus
from augur_signals.bus.redis_streams import RedisStreamsBus
from augur_signals.workers.bootstrap import (
    build_event_bus,
    load_runtime_configs,
    parse_shard_arg,
    resolve_replica_id,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_load_runtime_configs_parses_shipped_defaults() -> None:
    cfg = load_runtime_configs(REPO_ROOT / "config")
    assert cfg.bus.backend.kind == "memory"
    assert cfg.storage.backend.kind == "duckdb"
    assert cfg.observability.metrics.kind == "prometheus"


@pytest.mark.unit
def test_load_runtime_configs_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_runtime_configs(tmp_path)


@pytest.mark.unit
def test_build_event_bus_memory_rejects_loudly() -> None:
    cfg = BusConfig(backend=BackendBody(kind="memory"))
    with pytest.raises(RuntimeError, match="memory"):
        build_event_bus(cfg)


@pytest.mark.unit
def test_build_event_bus_nats_returns_nats_bus() -> None:
    cfg = BusConfig(backend=BackendBody(kind="nats"))
    assert isinstance(build_event_bus(cfg), NATSBus)


@pytest.mark.unit
def test_build_event_bus_redis_returns_redis_bus() -> None:
    cfg = BusConfig(backend=BackendBody(kind="redis"))
    assert isinstance(build_event_bus(cfg), RedisStreamsBus)


@pytest.mark.unit
def test_parse_shard_arg_happy_path() -> None:
    assert parse_shard_arg("0/2") == (0, 2)
    assert parse_shard_arg("3/4") == (3, 4)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["foo", "0", "0/0", "2/2", "-1/2", "a/b"])
def test_parse_shard_arg_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_shard_arg(bad)


@pytest.mark.unit
def test_resolve_replica_id_from_pod_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUGUR_REPLICA_ID", raising=False)
    monkeypatch.setenv("POD_NAME", "augur-feature-0")
    assert resolve_replica_id() == "augur-feature-0"


@pytest.mark.unit
def test_resolve_replica_id_augur_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUGUR_REPLICA_ID", "replica-a")
    monkeypatch.setenv("POD_NAME", "augur-feature-0")
    assert resolve_replica_id() == "replica-a"


@pytest.mark.unit
def test_resolve_replica_id_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUGUR_REPLICA_ID", raising=False)
    monkeypatch.delenv("POD_NAME", raising=False)
    with pytest.raises(RuntimeError, match="Replica id"):
        resolve_replica_id()
