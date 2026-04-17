"""Worker harness orchestrating connect → run → shutdown with heartbeat.

Every worker process builds a ``WorkerHarness`` from its main module
and calls ``run`` to enter the supervisory loop. The harness connects
to the event bus, optionally starts a heartbeat task, and drives the
worker's ``process_once`` coroutine until a shutdown signal (SIGINT /
SIGTERM) flips the stop flag. On shutdown it awaits the pending batch
then closes the bus.

The harness stays backend-agnostic: it consumes the ``EventBus``
protocol from ``bus/base.py`` and a ``HeartbeatEmitter`` protocol that
callers plug in with concrete implementations. Stateless workers pass
a no-op emitter; singletons pass a lock-holding emitter that renews
the distributed lock each beat.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from augur_signals._observability import MetricCounter, MetricGauge
from augur_signals.bus.base import EventBus


@runtime_checkable
class HeartbeatEmitter(Protocol):
    """Periodic side-effect fired by the harness' background task."""

    async def beat(self) -> bool:
        """Emit one heartbeat; return True to keep running, False to stop."""
        ...


class _NoHeartbeat:
    """Heartbeat emitter that never stops the loop; used by stateless workers."""

    async def beat(self) -> bool:
        return True


@dataclass(slots=True)
class WorkerHarness:
    """Supervisor for a single worker replica.

    Attributes:
        worker_kind: Short identifier used as a metric label and log
            field (``"feature"``, ``"detector"``, ``"dedup"``, ...).
        replica_id: Stable identifier for this specific replica. In
            Kubernetes this is the pod name; on bare-metal deployments
            operators supply it through an env var.
        bus: EventBus connection to open at startup and close on exit.
        main: Coroutine the harness drives to completion; the coroutine
            is expected to honour ``stop_event`` via ``should_stop``.
        heartbeat: Optional emitter whose ``beat`` fires every
            ``heartbeat_interval_seconds``. Defaults to a no-op.
        heartbeat_interval_seconds: Seconds between beats.
    """

    worker_kind: str
    replica_id: str
    bus: EventBus
    main: Callable[[WorkerHarness], Coroutine[Any, Any, None]]
    heartbeat: HeartbeatEmitter = field(default_factory=_NoHeartbeat)
    heartbeat_interval_seconds: float = 10.0
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _alive: MetricGauge | None = None
    _processed: MetricCounter | None = None

    def __post_init__(self) -> None:
        self._alive = MetricGauge("augur_worker_alive", ["worker_kind", "replica_id"])
        self._processed = MetricCounter(
            "augur_worker_processed_total", ["worker_kind", "replica_id"]
        )

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def record_processed(self, delta: float = 1.0) -> None:
        if self._processed is not None:
            self._processed.inc(delta, worker_kind=self.worker_kind, replica_id=self.replica_id)

    async def run(self) -> None:
        """Drive the worker main task with signals and a heartbeat loop."""
        self._install_signal_handlers()
        if self._alive is not None:
            self._alive.set(1.0, worker_kind=self.worker_kind, replica_id=self.replica_id)
        await self.bus.connect()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        main_task = asyncio.create_task(self.main(self))
        stop_task = asyncio.create_task(self._stop.wait())
        try:
            done, pending = await asyncio.wait(
                {main_task, heartbeat_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            _ = done
            for task in pending:
                task.cancel()
            self._stop.set()
            for task in pending:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            if self._alive is not None:
                self._alive.set(0.0, worker_kind=self.worker_kind, replica_id=self.replica_id)
            await self.bus.close()

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            keep_running = await self.heartbeat.beat()
            if not keep_running:
                self._stop.set()
                return
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.heartbeat_interval_seconds)
            except TimeoutError:
                continue

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                # Windows does not support signal handlers on the event
                # loop; the harness still runs and stops on Ctrl+C via
                # KeyboardInterrupt propagation.
                continue
