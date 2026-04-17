"""Tests for the distributed-runtime configuration loaders."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from augur_signals._config import load_config
from augur_signals._observability_config import ObservabilityConfig
from augur_signals.bus._config import BusConfig
from augur_signals.storage._config import StorageConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@pytest.mark.unit
def test_storage_toml_parses_with_defaults() -> None:
    cfg = load_config(CONFIG_DIR / "storage.toml", StorageConfig)
    assert cfg.backend.kind == "duckdb"
    assert cfg.backend.duckdb_path == "data/augur.duckdb"
    assert cfg.connection.pool_size == 20
    assert cfg.migration.dual_write_lag_alert_seconds == 10
    assert cfg.hypertable.signal_chunk_interval_days == 7
    assert cfg.compression.snapshot_compress_after_days == 7


@pytest.mark.unit
def test_storage_rejects_unknown_backend(tmp_path: Path) -> None:
    bad = tmp_path / "storage.toml"
    bad.write_text('[backend]\nkind = "sqlite"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(bad, StorageConfig)


@pytest.mark.unit
def test_storage_rejects_unknown_top_level_section(tmp_path: Path) -> None:
    bad = tmp_path / "storage.toml"
    bad.write_text(
        '[backend]\nkind = "duckdb"\n\n[unknown]\nfoo = 1\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_config(bad, StorageConfig)


@pytest.mark.unit
def test_bus_toml_parses_with_defaults() -> None:
    cfg = load_config(CONFIG_DIR / "bus.toml", BusConfig)
    assert cfg.backend.kind == "memory"
    assert cfg.backend.capacity == 256
    assert cfg.nats.subject_prefix == "augur"
    assert cfg.redis.stream_max_length == 100_000
    assert cfg.lock.ttl_seconds == 30
    assert cfg.lock.renew_interval_seconds == 10


@pytest.mark.unit
def test_bus_rejects_unknown_backend(tmp_path: Path) -> None:
    bad = tmp_path / "bus.toml"
    bad.write_text('[backend]\nkind = "kafka"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(bad, BusConfig)


@pytest.mark.unit
def test_bus_lock_renew_must_be_positive(tmp_path: Path) -> None:
    bad = tmp_path / "bus.toml"
    bad.write_text(
        '[backend]\nkind = "memory"\n\n[lock]\nttl_seconds = 30\nrenew_interval_seconds = 0\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_config(bad, BusConfig)


@pytest.mark.unit
def test_observability_toml_parses_with_defaults() -> None:
    cfg = load_config(CONFIG_DIR / "observability.toml", ObservabilityConfig)
    assert cfg.metrics.kind == "prometheus"
    assert cfg.metrics.prometheus_port == 9090
    assert cfg.traces.kind == "otlp"
    assert cfg.traces.sampling_ratio == 0.1
    assert cfg.logs.level == "INFO"


@pytest.mark.unit
def test_observability_sampling_ratio_bounded(tmp_path: Path) -> None:
    bad = tmp_path / "observability.toml"
    bad.write_text(
        '[traces]\nkind = "otlp"\nsampling_ratio = 1.5\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_config(bad, ObservabilityConfig)


@pytest.mark.unit
def test_observability_disabled_metrics_variant(tmp_path: Path) -> None:
    good = tmp_path / "observability.toml"
    good.write_text('[metrics]\nkind = "disabled"\n', encoding="utf-8")
    cfg = load_config(good, ObservabilityConfig)
    assert cfg.metrics.kind == "disabled"
