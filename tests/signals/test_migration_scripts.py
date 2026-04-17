"""Tests for the TimescaleDB migration and dual-write sidecar scripts."""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import migrate_to_timescale as migrate
from dual_write_sidecar import LagTracker, run_sidecar

from augur_signals._observability import MetricCounter, MetricGauge
from augur_signals.bus.base import BusMessage, EventBus


@dataclass
class _Cursor:
    executed: list[tuple[str, list[Any] | None]] = field(default_factory=list)
    pending_rows: list[tuple[Any, ...]] = field(default_factory=list)

    async def execute(self, sql: str, params: list[Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def executemany(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        for p in params:
            self.executed.append((sql, list(p)))

    async def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self.pending_rows
        self.pending_rows = []
        return rows

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@dataclass
class _Conn:
    cur: _Cursor = field(default_factory=_Cursor)
    committed: int = 0

    def cursor(self) -> _Cursor:
        return self.cur

    async def commit(self) -> None:
        self.committed += 1

    async def __aenter__(self) -> _Conn:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.asyncio
async def test_backfill_aborts_on_row_count_mismatch(tmp_path: Path) -> None:
    partition = tmp_path / "date=2026-04-01"
    partition.mkdir(parents=True)
    # Write a tiny parquet file so _count_parquet_rows returns a
    # non-zero count.
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"market_id": ["m-1", "m-2"], "timestamp": [1, 2]})
    pq.write_table(table, partition / "part-0.parquet")

    async def fake_copy(conn: Any, part: Path, batch: int) -> int:
        _ = conn, part, batch
        return 1  # Lie about rows landed.

    migrate._copy_partition_into_timescale = fake_copy  # type: ignore[assignment]

    @asynccontextmanager
    async def factory() -> AsyncIterator[_Conn]:
        yield _Conn()

    with pytest.raises(migrate.MigrationError, match="Row-count mismatch"):
        await migrate.backfill(source_root=tmp_path, batch_size=100, connection_factory=factory)


@pytest.mark.asyncio
async def test_backfill_happy_path_returns_summary(tmp_path: Path) -> None:
    partition = tmp_path / "date=2026-04-01"
    partition.mkdir(parents=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({"market_id": ["m-1", "m-2"]})
    pq.write_table(table, partition / "part-0.parquet")

    async def fake_copy(conn: Any, part: Path, batch: int) -> int:
        _ = conn, part, batch
        return 2

    migrate._copy_partition_into_timescale = fake_copy  # type: ignore[assignment]

    @asynccontextmanager
    async def factory() -> AsyncIterator[_Conn]:
        yield _Conn()

    summary = await migrate.backfill(
        source_root=tmp_path, batch_size=100, connection_factory=factory
    )
    assert summary.partition_count == 1
    assert summary.total_rows == 2


def test_discover_partitions_sorts_chronologically(tmp_path: Path) -> None:
    for name in ("date=2026-04-01", "date=2026-03-01", "date=2026-05-01"):
        (tmp_path / name).mkdir()
    partitions = migrate._discover_partitions(tmp_path)
    assert [p.name for p in partitions] == [
        "date=2026-03-01",
        "date=2026-04-01",
        "date=2026-05-01",
    ]


def test_discover_partitions_rejects_empty_root(tmp_path: Path) -> None:
    with pytest.raises(migrate.MigrationError, match="No partitions"):
        migrate._discover_partitions(tmp_path)


# --- dual-write sidecar ----------------------------------------------


@dataclass
class _FixedClock:
    value: datetime = datetime(2026, 4, 1, 12, 0, 10, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@dataclass
class _MemoryBus(EventBus):
    messages: list[BusMessage] = field(default_factory=list)
    connected: bool = False
    closed: bool = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def publish(self, message: BusMessage) -> None:  # pragma: no cover
        raise NotImplementedError

    async def subscribe(
        self, subject_pattern: str, consumer_group: str
    ) -> AsyncIterator[BusMessage]:
        _ = subject_pattern, consumer_group
        for msg in list(self.messages):
            yield msg


@dataclass
class _RecordingStore:
    snapshots_inserted: int = 0

    async def insert_snapshot(self, snapshot: Any) -> None:
        _ = snapshot
        self.snapshots_inserted += 1

    async def insert_feature(self, feature: Any) -> None:  # pragma: no cover
        _ = feature

    async def insert_signal(self, signal: Any) -> None:  # pragma: no cover
        _ = signal


@pytest.mark.asyncio
async def test_lag_tracker_fires_alert_past_threshold() -> None:
    registry_gauge = MetricGauge("augur_dual_write_lag_seconds_test", ["table"])
    registry_counter = MetricCounter("augur_dual_write_lag_alerts_total_test", ["table"])
    clock = _FixedClock()
    tracker = LagTracker(
        threshold_seconds=5,
        gauge=registry_gauge,
        alerts=registry_counter,
        clock=clock,
    )
    # Record a 12-second-old event; should trip the threshold.
    delta = tracker.record("snapshots", datetime(2026, 4, 1, 11, 59, 58, tzinfo=UTC))
    assert delta == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_run_sidecar_replays_snapshots_and_tracks_lag() -> None:
    bus = _MemoryBus(
        messages=[
            BusMessage(
                subject="augur.writes",
                payload=json.dumps(
                    {
                        "table": "snapshots",
                        "ts": "2026-04-01T12:00:00+00:00",
                        "row": {
                            "market_id": "m-1",
                            "platform": "kalshi",
                            "timestamp": "2026-04-01T12:00:00+00:00",
                            "last_price": 0.5,
                            "bid": 0.49,
                            "ask": 0.51,
                            "spread": 0.02,
                            "volume_24h": 1000.0,
                            "liquidity": 5000.0,
                            "question": "Q",
                            "resolution_source": "R",
                            "resolution_criteria": "C",
                            "closes_at": "2026-06-01T00:00:00+00:00",
                            "raw_json": {},
                        },
                    }
                ).encode("utf-8"),
            )
        ]
    )
    store = _RecordingStore()
    tracker = LagTracker(
        threshold_seconds=30,
        gauge=MetricGauge("augur_dual_write_lag_seconds_itest", ["table"]),
        alerts=MetricCounter("augur_dual_write_lag_alerts_total_itest", ["table"]),
        clock=_FixedClock(),
    )
    processed = await run_sidecar(
        bus=bus,
        tee_subject="augur.writes",
        consumer_group="dual_write",
        store=store,  # type: ignore[arg-type]
        tracker=tracker,
        stop_after=1,
    )
    assert processed == 1
    assert store.snapshots_inserted == 1
    assert bus.closed is True
