"""Tests for WorkerHarness, stateless bridge, shard routing, subject helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from augur_signals.bus.base import BusMessage, EventBus
from augur_signals.workers import subjects
from augur_signals.workers.harness import HeartbeatEmitter, WorkerHarness
from augur_signals.workers.sharding import owned_by, shard_index
from augur_signals.workers.stateless import ShardConfig, run_bridge


@dataclass
class _MemoryBus(EventBus):
    published: list[BusMessage] = field(default_factory=list)
    backlog: list[BusMessage] = field(default_factory=list)
    connected: bool = False
    closed: bool = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def publish(self, message: BusMessage) -> None:
        self.published.append(message)

    async def subscribe(
        self, subject_pattern: str, consumer_group: str
    ) -> AsyncIterator[BusMessage]:
        _ = subject_pattern, consumer_group
        for msg in list(self.backlog):
            yield msg


@pytest.mark.asyncio
async def test_harness_connects_runs_and_closes_bus() -> None:
    bus = _MemoryBus()
    ran = asyncio.Event()

    async def main(harness: WorkerHarness) -> None:
        ran.set()
        harness.request_stop()

    harness = WorkerHarness(
        worker_kind="unit",
        replica_id="r-0",
        bus=bus,
        main=main,
        heartbeat_interval_seconds=0.01,
    )
    await harness.run()
    assert bus.connected is True
    assert bus.closed is True
    assert ran.is_set()


@dataclass
class _Heart:
    ticks: int = 0
    stop_after: int = 3

    async def beat(self) -> bool:
        self.ticks += 1
        return self.ticks < self.stop_after


@pytest.mark.asyncio
async def test_heartbeat_returning_false_stops_the_loop() -> None:
    bus = _MemoryBus()
    heart: HeartbeatEmitter = _Heart(stop_after=2)

    async def main(harness: WorkerHarness) -> None:
        while not harness.should_stop():  # noqa: ASYNC110
            await asyncio.sleep(0.01)

    harness = WorkerHarness(
        worker_kind="singleton",
        replica_id="r-0",
        bus=bus,
        main=main,
        heartbeat=heart,
        heartbeat_interval_seconds=0.01,
    )
    await harness.run()
    assert harness.should_stop()


@pytest.mark.asyncio
async def test_run_bridge_consumes_and_publishes() -> None:
    bus = _MemoryBus()
    bus.backlog = [
        BusMessage(subject="augur.features.m-1", payload=b"1"),
        BusMessage(subject="augur.features.m-2", payload=b"2"),
    ]

    async def main(harness: WorkerHarness) -> None:
        async def _tx(value: bytes) -> list[bytes]:
            return [value + b"x"]

        await run_bridge(
            harness,
            input_pattern="augur.features.>",
            output_subject_builder=lambda _out: "augur.candidates.cusum",
            consumer_group="detector.cusum",
            deserialize=lambda b: b,
            transform=_tx,
            serialize=lambda v: v,
            trace_name="detector",
        )

    harness = WorkerHarness(
        worker_kind="detector",
        replica_id="r-0",
        bus=bus,
        main=main,
        heartbeat_interval_seconds=0.01,
    )
    await harness.run()
    payloads = [m.payload for m in bus.published]
    assert payloads == [b"1x", b"2x"]


@pytest.mark.asyncio
async def test_run_bridge_shard_filter_drops_foreign_keys() -> None:
    bus = _MemoryBus()
    bus.backlog = [
        BusMessage(subject="augur.features.m-1", payload=b"m-1"),
        BusMessage(subject="augur.features.m-2", payload=b"m-2"),
        BusMessage(subject="augur.features.m-3", payload=b"m-3"),
    ]

    # The replica pool size is 2; whichever replica owns the key sees
    # only messages whose shard_index(key, 2) == replica_id.
    replica_id = 0
    owned = [key for key in [b"m-1", b"m-2", b"m-3"] if owned_by(key.decode(), replica_id, 2)]

    async def main(harness: WorkerHarness) -> None:
        async def _tx(value: bytes) -> list[bytes]:
            return [value]

        await run_bridge(
            harness,
            input_pattern="augur.features.>",
            output_subject_builder=lambda _out: "augur.candidates.out",
            consumer_group="shard-test",
            deserialize=lambda b: b,
            transform=_tx,
            serialize=lambda v: v,
            shard_key=lambda v: v.decode(),
            shard_config=ShardConfig(replica_id=replica_id, replica_count=2),
            trace_name="shard",
        )

    harness = WorkerHarness(
        worker_kind="feature",
        replica_id="r-0",
        bus=bus,
        main=main,
        heartbeat_interval_seconds=0.01,
    )
    await harness.run()
    assert [m.payload for m in bus.published] == owned


@pytest.mark.unit
def test_shard_index_stable_and_in_range() -> None:
    assert shard_index("m-1", 1) == 0
    for key in ["a", "kalshi_fed_q2", "polymarket_yes"]:
        idx = shard_index(key, 8)
        assert 0 <= idx < 8


@pytest.mark.unit
def test_shard_index_rejects_zero_replica_count() -> None:
    with pytest.raises(ValueError, match="replica_count must be positive"):
        shard_index("key", 0)


@pytest.mark.unit
def test_subject_helpers_include_prefix() -> None:
    assert subjects.snapshots("augur", "kalshi", "m-1") == "augur.snapshots.kalshi.m-1"
    assert subjects.features("augur", "m-1") == "augur.features.m-1"
    assert subjects.candidates("augur", "cusum") == "augur.candidates.cusum"
    assert subjects.flagged_signals("augur") == "augur.flagged_signals"
    assert subjects.signals("augur") == "augur.signals"
    assert subjects.briefs("augur", "json") == "augur.briefs.json"
    assert subjects.snapshots_pattern("augur") == "augur.snapshots.>"
    assert subjects.snapshots_pattern("augur", "kalshi") == "augur.snapshots.kalshi.>"
