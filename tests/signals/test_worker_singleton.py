"""Tests for active-passive singleton worker failover."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from augur_signals.bus._config import LockBody
from augur_signals.bus._lock import InMemoryLock
from augur_signals.bus.base import BusMessage, EventBus
from augur_signals.workers.harness import WorkerHarness
from augur_signals.workers.singleton import (
    SingletonHeartbeat,
    SingletonRunner,
    acquire_active_role,
)


@dataclass
class _ManualClock:
    t: float = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@dataclass
class _MemoryBus(EventBus):
    connected: bool = False
    closed: bool = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def publish(self, message: BusMessage) -> None:  # pragma: no cover
        raise NotImplementedError

    async def subscribe(  # pragma: no cover
        self, subject_pattern: str, consumer_group: str
    ) -> AsyncIterator[BusMessage]:
        _ = subject_pattern, consumer_group
        if False:  # type: ignore[unreachable]
            yield


@pytest.mark.asyncio
async def test_acquire_active_role_returns_true_when_lock_free() -> None:
    lock = InMemoryLock()
    ok = await acquire_active_role(
        lock,
        "dedup",
        "replica-a",
        LockBody(ttl_seconds=30, renew_interval_seconds=10),
        wait_tick_seconds=0.0,
        max_wait_ticks=0,
    )
    assert ok is True


@pytest.mark.asyncio
async def test_acquire_active_role_gives_up_after_max_ticks() -> None:
    lock = InMemoryLock()
    await lock.acquire("dedup", "replica-a", ttl_seconds=30)
    ok = await acquire_active_role(
        lock,
        "dedup",
        "replica-b",
        LockBody(ttl_seconds=30, renew_interval_seconds=10),
        wait_tick_seconds=0.0,
        max_wait_ticks=2,
    )
    assert ok is False
    assert await lock.holder("dedup") == "replica-a"


@pytest.mark.asyncio
async def test_singleton_heartbeat_stops_when_lock_lost() -> None:
    clock = _ManualClock()
    lock = InMemoryLock(_clock=clock)
    await lock.acquire("dedup", "replica-a", ttl_seconds=30)
    heart = SingletonHeartbeat(
        lock=lock,
        lock_name="dedup",
        holder_id="replica-a",
        ttl_seconds=30,
    )
    assert await heart.beat() is True
    # Simulate failover: replica-b takes the lock after TTL expiry.
    clock.advance(40)
    await lock.acquire("dedup", "replica-b", ttl_seconds=30)
    assert await heart.beat() is False


@pytest.mark.asyncio
async def test_singleton_runner_releases_lock_on_shutdown() -> None:
    lock = InMemoryLock()
    bus = _MemoryBus()
    ran = asyncio.Event()

    async def main(harness: WorkerHarness) -> None:
        ran.set()
        harness.request_stop()

    runner = SingletonRunner(
        lock_name="dedup",
        bus=bus,
        lock=lock,
        config=LockBody(ttl_seconds=30, renew_interval_seconds=10),
        main=main,
        replica_id="replica-a",
    )
    await runner.run(wait_tick_seconds=0.0)
    assert ran.is_set()
    assert await lock.holder("dedup") is None


@pytest.mark.asyncio
async def test_singleton_runner_passive_peer_takes_over_on_failover() -> None:
    lock = InMemoryLock()
    bus_a = _MemoryBus()
    bus_b = _MemoryBus()
    b_ran = asyncio.Event()

    async def main_a(harness: WorkerHarness) -> None:
        # Active: exit immediately so the lock is released.
        harness.request_stop()

    async def main_b(harness: WorkerHarness) -> None:
        b_ran.set()
        harness.request_stop()

    runner_a = SingletonRunner(
        lock_name="dedup",
        bus=bus_a,
        lock=lock,
        config=LockBody(ttl_seconds=30, renew_interval_seconds=10),
        main=main_a,
        replica_id="replica-a",
    )
    runner_b = SingletonRunner(
        lock_name="dedup",
        bus=bus_b,
        lock=lock,
        config=LockBody(ttl_seconds=30, renew_interval_seconds=10),
        main=main_b,
        replica_id="replica-b",
    )
    await runner_a.run(wait_tick_seconds=0.0)
    await runner_b.run(wait_tick_seconds=0.0)
    assert b_ran.is_set()
