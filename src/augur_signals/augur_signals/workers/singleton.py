"""Active-passive singleton worker pair with distributed-lock failover.

Dedup and the LLM formatter run as one active instance with one passive
peer. The pair coordinates through a ``DistributedLock``:

* Both replicas boot and try to ``acquire`` the shared lock.
* Whoever wins is **active** and starts processing. It renews the lock
  every ``renew_interval_seconds``.
* The loser is **passive**; it sits in a retry loop checking whether
  the lock is available. It processes nothing until it takes over.
* If the active replica crashes or is partitioned, its lock TTL lapses
  and the passive's retry loop acquires, then begins processing.

``SingletonHeartbeat`` is the ``HeartbeatEmitter`` the WorkerHarness
binds to: each beat renews the lock; losing the lock flips the worker
into passive mode, which the harness observes through a ``False``
return and shuts down so the orchestrator restarts the process
(which then goes through the acquire loop again, this time winning).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from augur_signals._observability import MetricCounter, MetricGauge
from augur_signals.bus._config import LockBody
from augur_signals.bus._lock import DistributedLock
from augur_signals.bus.base import EventBus
from augur_signals.workers.harness import HeartbeatEmitter, WorkerHarness


@dataclass(slots=True)
class SingletonHeartbeat:
    """HeartbeatEmitter that renews a distributed lock each beat.

    Returning False from ``beat`` signals the harness to stop. This
    happens when the lock was lost (another replica acquired) or the
    lock backend raises a terminal error.
    """

    lock: DistributedLock
    lock_name: str
    holder_id: str
    ttl_seconds: int
    failover_counter: MetricCounter | None = None
    holder_gauge: MetricGauge | None = None

    async def beat(self) -> bool:
        still_holding = await self.lock.renew(self.lock_name, self.holder_id, self.ttl_seconds)
        if still_holding:
            if self.holder_gauge is not None:
                self.holder_gauge.set(
                    1.0,
                    singleton_kind=self.lock_name,
                    replica_id=self.holder_id,
                )
            return True
        if self.failover_counter is not None:
            self.failover_counter.inc(singleton_kind=self.lock_name)
        return False


async def acquire_active_role(
    lock: DistributedLock,
    lock_name: str,
    holder_id: str,
    config: LockBody,
    *,
    wait_tick_seconds: float = 1.0,
    max_wait_ticks: int | None = None,
) -> bool:
    """Block until this replica wins the lock; return True on acquire.

    Args:
        lock: The distributed lock to acquire.
        lock_name: Singleton role name (``"dedup"`` / ``"llm_formatter"``).
        holder_id: This replica's stable identifier.
        config: ``LockBody`` carrying TTL / renew interval.
        wait_tick_seconds: Poll cadence while passive.
        max_wait_ticks: Optional cap on ticks before giving up; None
            means wait forever (the production default). Tests pass a
            small cap so an unresolved passive role terminates the
            test.

    Returns:
        True if the replica acquired the lock. False only when
        *max_wait_ticks* is finite and exhausted.
    """
    ticks = 0
    while True:
        if await lock.acquire(lock_name, holder_id, config.ttl_seconds):
            return True
        if max_wait_ticks is not None and ticks >= max_wait_ticks:
            return False
        await asyncio.sleep(wait_tick_seconds)
        ticks += 1


@dataclass(slots=True)
class SingletonRunner:
    """Glue that turns a singleton workload into a ``WorkerHarness`` run.

    Attributes:
        lock_name: Singleton role name; matches the keys in the
            distributed lock backend.
        bus: EventBus connection used by the main coroutine.
        lock: DistributedLock coordinating active/passive.
        config: ``LockBody`` holding TTL and renew interval.
        main: Coroutine run while holding the active role.
    """

    lock_name: str
    bus: EventBus
    lock: DistributedLock
    config: LockBody
    main: Callable[[WorkerHarness], Coroutine[Any, Any, None]]
    replica_id: str = field(default_factory=lambda: str(uuid4()))

    async def run(self, *, wait_tick_seconds: float = 1.0) -> None:
        """Acquire, run main with heartbeat-driven renewal, release."""
        acquired = await acquire_active_role(
            self.lock,
            self.lock_name,
            self.replica_id,
            self.config,
            wait_tick_seconds=wait_tick_seconds,
        )
        if not acquired:
            return
        heartbeat: HeartbeatEmitter = SingletonHeartbeat(
            lock=self.lock,
            lock_name=self.lock_name,
            holder_id=self.replica_id,
            ttl_seconds=self.config.ttl_seconds,
            failover_counter=MetricCounter("augur_failover_total", ["singleton_kind"]),
            holder_gauge=MetricGauge(
                "augur_singleton_lock_holder", ["singleton_kind", "replica_id"]
            ),
        )
        harness = WorkerHarness(
            worker_kind=f"singleton.{self.lock_name}",
            replica_id=self.replica_id,
            bus=self.bus,
            main=self.main,
            heartbeat=heartbeat,
            heartbeat_interval_seconds=float(self.config.renew_interval_seconds),
        )
        try:
            await harness.run()
        finally:
            await self.lock.release(self.lock_name, self.replica_id)
