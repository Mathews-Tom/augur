"""Tests for the TimescaleDB storage adapter.

The tests use a recording stub in place of ``psycopg.AsyncConnection``
so the SQL the adapter issues can be inspected without running a real
TimescaleDB instance. CI opts into full integration tests against a
live TimescaleDB container under ``@pytest.mark.integration`` (added in
a follow-up commit alongside docker-compose fixtures).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from augur_signals.models import (
    ManipulationFlag,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)
from augur_signals.storage._config import (
    CompressionBody,
    HypertableBody,
    RetentionBody,
)
from augur_signals.storage.timescaledb_store import TimescaleDBStore


@dataclass
class _RecordingCursor:
    executed: list[tuple[str, list[Any] | None]] = field(default_factory=list)
    pending_rows: list[tuple[Any, ...]] = field(default_factory=list)

    async def execute(self, sql: str, params: list[Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> tuple[Any, ...] | None:
        if not self.pending_rows:
            return None
        return self.pending_rows.pop(0)

    async def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self.pending_rows
        self.pending_rows = []
        return rows

    async def __aenter__(self) -> _RecordingCursor:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@dataclass
class _RecordingConnection:
    cursor_: _RecordingCursor = field(default_factory=_RecordingCursor)
    committed: int = 0
    closed: bool = False

    def cursor(self) -> _RecordingCursor:
        return self.cursor_

    async def commit(self) -> None:
        self.committed += 1

    async def close(self) -> None:
        self.closed = True


def _store(conn: _RecordingConnection) -> TimescaleDBStore:
    return TimescaleDBStore(
        conn,  # type: ignore[arg-type]
        hypertable=HypertableBody(),
        retention=RetentionBody(),
        compression=CompressionBody(),
    )


def _statements(conn: _RecordingConnection) -> list[str]:
    return [sql.strip().split("\n", maxsplit=1)[0] for sql, _ in conn.cursor_.executed]


@pytest.mark.asyncio
async def test_initialize_creates_schema_and_hypertables() -> None:
    conn = _RecordingConnection()
    store = _store(conn)
    await store.initialize()
    joined = "\n".join(sql for sql, _ in conn.cursor_.executed)
    # Schema DDL runs first, then hypertables, then compression, then
    # retention, then the schema_version row lands via INSERT ON CONFLICT.
    assert "CREATE TABLE IF NOT EXISTS snapshots" in joined
    assert "create_hypertable" in joined
    assert "add_compression_policy" in joined
    assert "add_retention_policy" in joined
    assert "INSERT INTO schema_version" in joined
    assert conn.committed == 1


@pytest.mark.asyncio
async def test_hypertable_specs_match_configuration() -> None:
    conn = _RecordingConnection()
    store = _store(conn)
    specs = {spec.table: spec for spec in store.hypertable_specs()}
    assert specs["snapshots"].time_column == "timestamp"
    assert specs["snapshots"].chunk_interval_days == 1
    assert specs["snapshots"].segment_by == "market_id, platform"
    assert specs["signals"].time_column == "detected_at"
    assert specs["signals"].chunk_interval_days == 7
    assert specs["features"].retention_days == 30


@pytest.mark.asyncio
async def test_retention_zero_skips_retention_policy() -> None:
    conn = _RecordingConnection()
    store = TimescaleDBStore(
        conn,  # type: ignore[arg-type]
        hypertable=HypertableBody(),
        retention=RetentionBody(
            snapshot_retention_days=0,
            feature_retention_days=0,
            signal_retention_days=0,
        ),
        compression=CompressionBody(),
    )
    await store.initialize()
    joined = "\n".join(sql for sql, _ in conn.cursor_.executed)
    assert "add_retention_policy" not in joined
    assert "add_compression_policy" in joined  # compression still applies


@pytest.mark.asyncio
async def test_insert_snapshot_upserts_with_conflict_clause() -> None:
    conn = _RecordingConnection()
    store = _store(conn)
    snap = MarketSnapshot(
        market_id="m-1",
        platform="kalshi",
        timestamp=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        last_price=0.5,
        bid=0.49,
        ask=0.51,
        spread=0.02,
        volume_24h=1000.0,
        liquidity=5000.0,
        question="Will the Fed raise rates?",
        resolution_source="Federal Reserve",
        resolution_criteria="YES if rate rises.",
        raw_json={"source": "kalshi"},
        closes_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    await store.insert_snapshot(snap)
    sql, params = conn.cursor_.executed[0]
    assert "INSERT INTO snapshots" in sql
    assert "ON CONFLICT (market_id, platform, timestamp)" in sql
    assert params is not None
    assert params[0] == "m-1"
    assert json.loads(params[-2]) == {"source": "kalshi"}
    assert conn.committed == 1


@pytest.mark.asyncio
async def test_insert_signal_writes_signal_and_manipulation_flags() -> None:
    conn = _RecordingConnection()
    store = _store(conn)
    signal = MarketSignal(
        signal_id=new_signal_id(),
        market_id="m-1",
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.9,
        direction=1,
        confidence=0.8,
        fdr_adjusted=True,
        detected_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        manipulation_flags=[ManipulationFlag.SINGLE_COUNTERPARTY_CONCENTRATION],
        raw_features={"calibration_provenance": "d@identity_v0"},
    )
    await store.insert_signal(signal)
    statements = _statements(conn)
    # Two commits: one for the signal row, one for the flag row.
    assert any("INSERT INTO signals" in s for s in statements)
    assert any("INSERT INTO manipulation_flags" in s for s in statements)
    assert conn.committed == 2


@pytest.mark.asyncio
async def test_latest_snapshot_returns_none_for_empty_result() -> None:
    conn = _RecordingConnection()
    store = _store(conn)
    result = await store.latest_snapshot("m-1")
    assert result is None


@pytest.mark.asyncio
async def test_signals_in_window_no_markets_short_circuits() -> None:
    conn = _RecordingConnection()
    store = _store(conn)
    result = await store.signals_in_window(
        [], datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
    )
    assert result == []
    assert conn.cursor_.executed == []


@pytest.mark.asyncio
async def test_close_propagates_to_connection() -> None:
    conn = _RecordingConnection()
    store = _store(conn)
    await store.close()
    assert conn.closed is True


def test_quote_ident_rejects_non_alphanumeric_identifier() -> None:
    with pytest.raises(ValueError, match="Refusing to quote"):
        TimescaleDBStore._quote_ident("snapshots; DROP TABLE")
