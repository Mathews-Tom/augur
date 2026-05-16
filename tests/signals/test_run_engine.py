"""Tests for the single-process engine runner."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from augur_signals.ingestion.base import RawMarketData


def _load_run_engine() -> object:
    path = Path("scripts/run_engine.py")
    spec = importlib.util.spec_from_file_location("run_engine", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_engine"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_run_engine_rejects_empty_active_watchlist(tmp_path: Path) -> None:
    module = _load_run_engine()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "markets.toml").write_text(
        """
[[markets]]
id = "inactive"
platform = "polymarket"
platform_market_id = "condition-id"
category = "monetary_policy"
active = false
poll_priority = "normal"
""",
        encoding="utf-8",
    )
    runtime_config = module.RuntimeConfig(
        config_dir=config_dir,
        data_dir=tmp_path / "data",
        once=True,
        poll_seconds=1.0,
        trade_lookback_seconds=300,
    )

    with pytest.raises(RuntimeError, match="no active markets"):
        module._build_runtime(runtime_config)


@pytest.mark.unit
def test_select_market_remaps_platform_id_to_config_id() -> None:
    module = _load_run_engine()
    market = module.MarketEntry(
        id="macro-fed-cut",
        platform="polymarket",
        platform_market_id="condition-id",
        category="monetary_policy",
        active=True,
        poll_priority="normal",
    )
    raw = RawMarketData(
        market_id="condition-id",
        platform="polymarket",
        fetched_at=datetime(2026, 5, 17, tzinfo=UTC),
        payload={"question": "Will rates fall?"},
    )

    selected = module._select_market([raw], market)

    assert selected.market_id == "macro-fed-cut"
    assert selected.payload == raw.payload
