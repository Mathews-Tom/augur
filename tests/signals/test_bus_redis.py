"""Tests for the Redis Streams EventBus adapter using fakeredis."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from augur_signals.bus._config import RedisBody
from augur_signals.bus.base import BusMessage
from augur_signals.bus.redis_streams import RedisLock, RedisStreamsBus


@pytest.fixture
def redis_client() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


@pytest.mark.asyncio
async def test_redis_streams_publish_and_subscribe_roundtrip(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    config = RedisBody(url_env="IGNORED", stream_max_length=100, block_ms=50)
    bus = RedisStreamsBus(config, client=redis_client)
    await bus.connect()

    subject = "augur.signals"
    await bus.publish(BusMessage(subject=subject, payload=b"hello"))
    await bus.publish(BusMessage(subject=subject, payload=b"world", headers={"trace_id": "abc"}))

    received: list[BusMessage] = []

    async def consume() -> None:
        async for msg in bus.subscribe(subject, "test-group"):
            received.append(msg)
            if len(received) >= 2:
                break

    await asyncio.wait_for(consume(), timeout=2.0)

    assert [m.payload for m in received] == [b"hello", b"world"]
    assert received[1].headers == {"trace_id": "abc"}

    await bus.close()


@pytest.mark.asyncio
async def test_redis_streams_xack_marks_processed_entries(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    """Ack is deferred to the next iteration; break leaves the current
    yielded message pending for redelivery (at-least-once semantics).
    """
    config = RedisBody(url_env="IGNORED", stream_max_length=100, block_ms=50)
    bus = RedisStreamsBus(config, client=redis_client)
    await bus.connect()

    subject = "augur.flagged_signals"
    await bus.publish(BusMessage(subject=subject, payload=b"one"))
    await bus.publish(BusMessage(subject=subject, payload=b"two"))
    await bus.publish(BusMessage(subject=subject, payload=b"three"))

    received: list[bytes] = []

    async def consume() -> None:
        async for msg in bus.subscribe(subject, "test-group"):
            received.append(msg.payload)
            if len(received) >= 3:
                # Break at msg #3. Expected: #1 and #2 were acked at
                # the top of the iterations that yielded #2 and #3
                # respectively. #3 stays pending because we broke
                # before re-entering the loop.
                break

    await asyncio.wait_for(consume(), timeout=2.0)

    summary = await redis_client.xpending(subject, "augur.test-group")
    pending = summary.get("pending") if isinstance(summary, dict) else summary[0]
    assert pending == 1

    await bus.close()


@pytest.mark.asyncio
async def test_redis_streams_repeated_connect_is_idempotent(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    config = RedisBody(url_env="IGNORED")
    bus = RedisStreamsBus(config, client=redis_client)
    await bus.connect()
    await bus.connect()
    await bus.publish(BusMessage(subject="augur.ops.events", payload=b"ping"))
    await bus.close()


@pytest.mark.asyncio
async def test_redis_lock_acquire_and_renew_and_release(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    lock = RedisLock(client=redis_client, key_prefix="augur.lock.")

    assert await lock.acquire("dedup", "replica-a", ttl_seconds=30) is True
    assert await lock.acquire("dedup", "replica-b", ttl_seconds=30) is False
    assert await lock.holder("dedup") == "replica-a"
    assert await lock.renew("dedup", "replica-a", ttl_seconds=30) is True
    assert await lock.renew("dedup", "replica-b", ttl_seconds=30) is False
    await lock.release("dedup", "replica-a")
    assert await lock.holder("dedup") is None


@pytest.mark.asyncio
async def test_redis_lock_release_by_non_owner_is_noop(
    redis_client: fakeredis.aioredis.FakeRedis,
) -> None:
    lock = RedisLock(client=redis_client, key_prefix="augur.lock.")
    await lock.acquire("llm", "replica-a", ttl_seconds=30)
    await lock.release("llm", "replica-b")
    assert await lock.holder("llm") == "replica-a"
