"""Tests for the distributed lock protocol and in-memory backend."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from augur_signals.bus._lock import InMemoryLock


@dataclass
class _ManualClock:
    t: float = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.mark.asyncio
async def test_acquire_succeeds_when_lock_free() -> None:
    lock = InMemoryLock()
    assert await lock.acquire("dedup", "replica-a", ttl_seconds=30) is True
    assert await lock.holder("dedup") == "replica-a"


@pytest.mark.asyncio
async def test_acquire_fails_when_another_holder_active() -> None:
    lock = InMemoryLock()
    await lock.acquire("dedup", "replica-a", ttl_seconds=30)
    assert await lock.acquire("dedup", "replica-b", ttl_seconds=30) is False


@pytest.mark.asyncio
async def test_acquire_succeeds_after_ttl_expires() -> None:
    clock = _ManualClock()
    lock = InMemoryLock(_clock=clock)
    await lock.acquire("dedup", "replica-a", ttl_seconds=30)
    clock.advance(31)
    assert await lock.acquire("dedup", "replica-b", ttl_seconds=30) is True
    assert await lock.holder("dedup") == "replica-b"


@pytest.mark.asyncio
async def test_renew_extends_ttl_when_still_owner() -> None:
    clock = _ManualClock()
    lock = InMemoryLock(_clock=clock)
    await lock.acquire("dedup", "replica-a", ttl_seconds=30)
    clock.advance(20)
    assert await lock.renew("dedup", "replica-a", ttl_seconds=30) is True
    clock.advance(25)
    # Would have expired without renew, still held.
    assert await lock.holder("dedup") == "replica-a"


@pytest.mark.asyncio
async def test_renew_rejects_stale_holder() -> None:
    clock = _ManualClock()
    lock = InMemoryLock(_clock=clock)
    await lock.acquire("dedup", "replica-a", ttl_seconds=30)
    clock.advance(31)
    await lock.acquire("dedup", "replica-b", ttl_seconds=30)
    assert await lock.renew("dedup", "replica-a", ttl_seconds=30) is False


@pytest.mark.asyncio
async def test_release_is_noop_for_non_owner() -> None:
    lock = InMemoryLock()
    await lock.acquire("dedup", "replica-a", ttl_seconds=30)
    await lock.release("dedup", "replica-b")
    assert await lock.holder("dedup") == "replica-a"


@pytest.mark.asyncio
async def test_release_drops_key_for_owner() -> None:
    lock = InMemoryLock()
    await lock.acquire("dedup", "replica-a", ttl_seconds=30)
    await lock.release("dedup", "replica-a")
    assert await lock.holder("dedup") is None


@pytest.mark.asyncio
async def test_same_holder_reacquire_is_idempotent() -> None:
    lock = InMemoryLock()
    assert await lock.acquire("dedup", "replica-a", ttl_seconds=30) is True
    assert await lock.acquire("dedup", "replica-a", ttl_seconds=30) is True
