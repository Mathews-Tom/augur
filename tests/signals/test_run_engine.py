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
        feature_warmup_size=50,
        summary_every_cycles=1,
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
        mode="once",
        cycle=1,
        storage="duckdb:data/augur.duckdb",
        active_markets=2,
        platforms=("polymarket:2",),
        snapshots=[snapshot],
        trades={"crypto-market": [trade], "macro-market": []},
        features={},
        signal_count=0,
        feature_warmup_size=50,
    )
    module._emit_summary(summary)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "augur run summary: status=ok mode=once cycle=1 storage=duckdb:data/augur.duckdb\n"
        "  markets: active=2 platforms=polymarket:2 snapshots=1\n"
        "  outputs: trades=1 features=0 signals=0\n"
        "  note: feature buffers are still warming; "
        "configured warmup is 50 observations per market, "
        "estimated remaining cycles=49, and --once starts a fresh in-memory buffer\n"
    )


@pytest.mark.unit
def test_continuous_summary_omits_warmup_note_after_features(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_engine()
    summary = module.CycleSummary(
        mode="continuous",
        cycle=5,
        storage="duckdb:data/augur.duckdb",
        active_markets=2,
        platforms=("polymarket:2",),
        snapshots=2,
        trades=0,
        features=2,
        signals=0,
        feature_warmup_size=5,
        warmup_remaining_cycles=0,
    )

    module._emit_summary(summary)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "augur run summary: status=ok mode=continuous cycle=5 storage=duckdb:data/augur.duckdb\n"
        "  markets: active=2 platforms=polymarket:2 snapshots=2\n"
        "  outputs: trades=0 features=2 signals=0\n"
    )


@pytest.mark.unit
def test_parse_args_accepts_smoke_warmup_override() -> None:
    module = _load_run_engine()

    config = module._parse_args(
        ["--once", "--feature-warmup-size", "5", "--summary-every-cycles", "3"]
    )

    assert config.once is True
    assert config.feature_warmup_size == 5
    assert config.summary_every_cycles == 3


@pytest.mark.unit
def test_main_handles_keyboard_interrupt_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_engine()

    def raise_interrupt(_: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "_run", lambda _: object())
    monkeypatch.setattr(module.asyncio, "run", raise_interrupt)

    rc = module.main(["--once"])

    captured = capsys.readouterr()
    assert rc == 130
    assert captured.out == ""
    assert captured.err == "run_engine stopped: interrupted\n"


@pytest.mark.unit
def test_platform_counts_sorts_by_platform() -> None:
    module = _load_run_engine()
    markets = [
        module.MarketEntry(
            id="poly-1",
            platform="polymarket",
            platform_market_id="condition-id-1",
            category="crypto_protocol",
            active=True,
            poll_priority="normal",
        ),
        module.MarketEntry(
            id="kalshi-1",
            platform="kalshi",
            platform_market_id="KALSHI-1",
            category="monetary_policy",
            active=True,
            poll_priority="normal",
        ),
        module.MarketEntry(
            id="poly-2",
            platform="polymarket",
            platform_market_id="condition-id-2",
            category="crypto_protocol",
            active=True,
            poll_priority="normal",
        ),
    ]

    assert module._platform_counts(markets) == ("kalshi:1", "polymarket:2")
