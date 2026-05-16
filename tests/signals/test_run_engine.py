"""Tests for the single-process engine runner."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from augur_signals.ingestion.base import RawMarketData, RawTrade
from augur_signals.models import MarketSnapshot


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


@pytest.mark.unit
def test_orderbook_market_id_uses_polymarket_primary_clob_token() -> None:
    module = _load_run_engine()
    market = module.MarketEntry(
        id="crypto-market",
        platform="polymarket",
        platform_market_id="condition-id",
        category="crypto_protocol",
        active=True,
        poll_priority="normal",
    )
    raw = RawMarketData(
        market_id="crypto-market",
        platform="polymarket",
        fetched_at=datetime(2026, 5, 17, tzinfo=UTC),
        payload={"clob_token_ids": ["yes-token", "no-token"]},
    )

    assert module._orderbook_market_id(raw, market) == "yes-token"


@pytest.mark.unit
def test_orderbook_market_id_keeps_kalshi_market_id() -> None:
    module = _load_run_engine()
    market = module.MarketEntry(
        id="kalshi-fed",
        platform="kalshi",
        platform_market_id="FED-2026",
        category="monetary_policy",
        active=True,
        poll_priority="normal",
    )
    raw = RawMarketData(
        market_id="kalshi-fed",
        platform="kalshi",
        fetched_at=datetime(2026, 5, 17, tzinfo=UTC),
        payload={},
    )

    assert module._orderbook_market_id(raw, market) == "FED-2026"


@pytest.mark.unit
def test_once_summary_counts_cycle_outputs(capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_run_engine()
    snapshot = MarketSnapshot(
        market_id="crypto-market",
        platform="polymarket",
        timestamp=datetime(2026, 5, 17, tzinfo=UTC),
        last_price=0.42,
        bid=0.41,
        ask=0.43,
        spread=0.02,
        volume_24h=1000.0,
        liquidity=500.0,
        question="Will X happen?",
        resolution_source=None,
        resolution_criteria=None,
        closes_at=None,
        raw_json={},
    )
    trade = RawTrade(
        market_id="crypto-market",
        platform="polymarket",
        timestamp=datetime(2026, 5, 17, tzinfo=UTC),
        price=0.42,
        size=10.0,
        side="buy",
        counterparty=None,
    )

    summary = module._summarize_cycle(
        active_markets=2,
        snapshots=[snapshot],
        trades={"crypto-market": [trade], "macro-market": []},
        features={},
        signal_count=0,
    )
    module._emit_once_summary(summary)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "augur run summary: active_markets=2 snapshots=1 trades=1 features=0 signals=0\n"
    )
