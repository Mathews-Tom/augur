"""Tests for the TOML configuration loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from augur_signals._config import load_config


class _Engine(BaseModel):
    bus_capacity: int
    storage_path: str
    log_level: str


class _Root(BaseModel):
    engine: _Engine


@pytest.mark.unit
def test_load_config_parses_valid_toml(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        '[engine]\nbus_capacity = 256\nstorage_path = "data/augur.duckdb"\nlog_level = "INFO"\n',
        encoding="utf-8",
    )

    result = load_config(path, _Root)

    assert result.engine.bus_capacity == 256
    assert result.engine.storage_path == "data/augur.duckdb"
    assert result.engine.log_level == "INFO"


@pytest.mark.unit
def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "absent.toml"
    with pytest.raises(FileNotFoundError, match=r"absent\.toml"):
        load_config(missing, _Root)


@pytest.mark.unit
def test_load_config_validation_error_surfaces(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(
        '[engine]\nbus_capacity = "not-an-int"\nstorage_path = "/tmp"\nlog_level = "INFO"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_config(path, _Root)
