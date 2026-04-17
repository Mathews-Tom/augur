"""Distributed lock primitives for active-passive singleton workers.

Dedup and the LLM formatter cannot shard; Phase 5 runs each as an
active instance with one passive peer. The pair coordinates via a
named lock stored in the message bus's metadata store:

* NATS: JetStream KV bucket (`DistributedLock` uses
  `kv.create`/`kv.update` with TTL).
* Redis: `SET key value NX EX ttl` for acquire; a Lua CAS script
  for renew/release to avoid racing another holder.

The protocol is minimal: `acquire` returns True on success, `renew`
extends the TTL, `release` drops the key only if the caller still
holds it. A single per-bus-backend implementation is registered with
`_BACKEND` at engine startup; unit tests inject `InMemoryLock`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class LockError(RuntimeError):
    """Raised when the lock backend rejects an operation terminally."""


@runtime_checkable
class DistributedLock(Protocol):
    """Coordinates active-passive singleton ownership across processes.

    The lock identity is `(name, holder_id)`: `name` identifies the
    singleton role (`"dedup"` or `"llm_formatter"`) and
    `holder_id` identifies the replica attempting to hold it. Each
    replica generates its own `holder_id` at process start; the
    surviving peer on failover observes the abandoned lock TTL expire
    and acquires on the next attempt.
    """

    async def acquire(self, name: str, holder_id: str, ttl_seconds: int) -> bool:
        """Try to acquire *name* for *holder_id*; return True on success."""
        ...

    async def renew(self, name: str, holder_id: str, ttl_seconds: int) -> bool:
        """Extend the TTL; return True if *holder_id* still owns *name*."""
        ...

    async def release(self, name: str, holder_id: str) -> None:
        """Release *name* iff owned by *holder_id*. No-op otherwise."""
        ...

    async def holder(self, name: str) -> str | None:
        """Return the current holder, or None if the lock is free."""
        ...


@dataclass(slots=True)
class _LockState:
    holder: str
    expires_at: float


@dataclass(slots=True)
class InMemoryLock:
    """Single-process reference lock.

    Used by tests and by single-process deployments that still exercise
    the active-passive pair code paths (for example, during local
    smoke tests where both the active and passive live in the same
    process). The lock honours TTLs against an injected clock so tests
    can simulate failover without real time passing.
    """

    _locks: dict[str, _LockState] = field(default_factory=dict)
    _mutex: asyncio.Lock = field(default_factory=asyncio.Lock)
    _clock: _Clock | None = None

    def __post_init__(self) -> None:
        if self._clock is None:
            self._clock = _WallClock()

    async def acquire(self, name: str, holder_id: str, ttl_seconds: int) -> bool:
        async with self._mutex:
            now = self._now()
            state = self._locks.get(name)
            if state is not None and state.expires_at > now and state.holder != holder_id:
                return False
            self._locks[name] = _LockState(holder=holder_id, expires_at=now + float(ttl_seconds))
            return True

    async def renew(self, name: str, holder_id: str, ttl_seconds: int) -> bool:
        async with self._mutex:
            state = self._locks.get(name)
            if state is None or state.holder != holder_id:
                return False
            state.expires_at = self._now() + float(ttl_seconds)
            return True

    async def release(self, name: str, holder_id: str) -> None:
        async with self._mutex:
            state = self._locks.get(name)
            if state is not None and state.holder == holder_id:
                del self._locks[name]

    async def holder(self, name: str) -> str | None:
        async with self._mutex:
            state = self._locks.get(name)
            if state is None or state.expires_at <= self._now():
                return None
            return state.holder

    def _now(self) -> float:
        clock = self._clock
        assert clock is not None  # noqa: S101 — init guarantees non-None
        return clock.now()


@runtime_checkable
class _Clock(Protocol):
    def now(self) -> float: ...


class _WallClock:
    def now(self) -> float:
        import time

        return time.monotonic()
