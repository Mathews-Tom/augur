"""Redis Streams adapter for the EventBus protocol.

The adapter maps each Augur subject to one Redis stream and uses
consumer groups for at-least-once semantics. `XADD` writes the
payload as a hash field (`p`) with optional headers under `h.*`;
`XREADGROUP` pulls entries and `XACK` acknowledges on successful
processing.

Redis supports subject *patterns* only through multi-stream watches
(`XREAD` against many streams). The adapter takes the literal
subject for now since the Phase 5 subject layout uses a static set of
stream names (`augur.snapshots.<platform>.<market_id>` becomes a
single stream keyed by full subject). A fan-in pattern needs a broker
upgrade — out of scope for Phase 5.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from augur_signals.bus._config import RedisBody
from augur_signals.bus._lock import DistributedLock, LockError
from augur_signals.bus.base import BusError, BusMessage, EventBus

if TYPE_CHECKING:
    from redis.asyncio import Redis


def _encode_message(message: BusMessage) -> dict[str | bytes, str | bytes]:
    fields: dict[str | bytes, str | bytes] = {"p": message.payload}
    if message.headers:
        for key, value in message.headers.items():
            fields[f"h.{key}"] = value.encode("utf-8")
    return fields


def _decode_message(subject: str, fields: dict[bytes | str, bytes | str]) -> BusMessage:
    payload = _coerce_bytes(fields[b"p"] if b"p" in fields else fields["p"])
    headers: dict[str, str] = {}
    for key, value in fields.items():
        key_str = key.decode("utf-8") if isinstance(key, bytes) else key
        if key_str.startswith("h."):
            headers[key_str[2:]] = value.decode("utf-8") if isinstance(value, bytes) else value
    return BusMessage(
        subject=subject,
        payload=payload,
        headers=headers or None,
    )


def _coerce_bytes(value: bytes | str) -> bytes:
    return value if isinstance(value, bytes) else value.encode("utf-8")


class RedisStreamsBus(EventBus):
    """EventBus backed by Redis Streams.

    Attributes:
        config: Validated `RedisBody` loaded from `config/bus.toml`.
    """

    def __init__(self, config: RedisBody, *, client: Redis | None = None) -> None:
        self.config = config
        self._client = client
        self._connected = client is not None

    async def connect(self) -> None:
        if self._connected:
            return
        if self._client is None:
            import os

            import redis.asyncio as redis_asyncio

            url = os.environ[self.config.url_env]
            self._client = redis_asyncio.from_url(url)
        self._connected = True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._connected = False

    async def publish(self, message: BusMessage) -> None:
        if self._client is None:
            raise BusError("RedisStreamsBus.connect() must be called before publish()")
        # redis-py's FieldT / EncodableT TypeVars pin to a broader union
        # than our helper returns; cast through Any so the adapter stays
        # generic over str|bytes keys without duplicating the union.
        fields: Any = _encode_message(message)
        await self._client.xadd(
            message.subject,
            fields,
            maxlen=self.config.stream_max_length,
            approximate=True,
        )

    async def subscribe(
        self, subject_pattern: str, consumer_group: str
    ) -> AsyncIterator[BusMessage]:
        if self._client is None:
            raise BusError("RedisStreamsBus.connect() must be called before subscribe()")
        group = f"{self.config.consumer_group_prefix}.{consumer_group}"
        consumer = f"{group}-consumer"
        try:
            await self._client.xgroup_create(subject_pattern, group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise BusError(f"Failed to create consumer group {group}") from exc
        # Redis consumer groups persist across restarts; nothing to
        # tear down in a finally block. The loop exits on cancellation
        # propagated from the caller's async-for.
        while True:
            entries = await self._client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={subject_pattern: ">"},
                count=1,
                block=self.config.block_ms,
            )
            if not entries:
                # Yield control so an outer cancellation can fire.
                await asyncio.sleep(0)
                continue
            for _stream, messages in entries:
                for msg_id, fields in messages:
                    message = _decode_message(subject_pattern, fields)
                    yield message
                    await self._client.xack(subject_pattern, group, msg_id)


class RedisLock(DistributedLock):
    """Distributed lock backed by Redis `SET NX EX` with CAS renew/release.

    `acquire` uses `SET key value NX EX ttl` which is atomic at the
    server. `renew` and `release` use `WATCH` + `MULTI` / EXEC
    so the current holder check and the mutating command commit
    together; a concurrent owner swap invalidates the transaction and
    the operation is aborted without side effects. Using WATCH rather
    than `EVAL` keeps the adapter compatible with Redis deployments
    that restrict scripting (and with in-memory fakes that do not ship
    a Lua interpreter).
    """

    def __init__(self, *, client: Redis, key_prefix: str = "augur.lock.") -> None:
        self._client = client
        self._key_prefix = key_prefix

    def _key(self, name: str) -> str:
        return f"{self._key_prefix}{name}"

    @staticmethod
    def _matches(current: bytes | str | None, holder_id: str) -> bool:
        if current is None:
            return False
        value = current.decode("utf-8") if isinstance(current, bytes) else current
        return value == holder_id

    async def acquire(self, name: str, holder_id: str, ttl_seconds: int) -> bool:
        result = await self._client.set(self._key(name), holder_id, nx=True, ex=ttl_seconds)
        return bool(result)

    async def renew(self, name: str, holder_id: str, ttl_seconds: int) -> bool:
        # redis-py's pipeline helpers are untyped; cast through Any so the
        # CAS retry stays readable without per-call mypy suppressions.
        pipe: Any
        async with self._client.pipeline() as pipe:
            key = self._key(name)
            while True:
                try:
                    await pipe.watch(key)
                    current = await pipe.get(key)
                    if not self._matches(current, holder_id):
                        await pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.pexpire(key, ttl_seconds * 1000)
                    result = await pipe.execute()
                    return bool(result and result[0])
                except Exception as exc:
                    if "WatchError" in type(exc).__name__:
                        continue
                    raise

    async def release(self, name: str, holder_id: str) -> None:
        pipe: Any
        async with self._client.pipeline() as pipe:
            key = self._key(name)
            while True:
                try:
                    await pipe.watch(key)
                    current = await pipe.get(key)
                    if not self._matches(current, holder_id):
                        await pipe.unwatch()
                        return
                    pipe.multi()
                    pipe.delete(key)
                    await pipe.execute()
                    return
                except Exception as exc:
                    if "WatchError" in type(exc).__name__:
                        continue
                    raise

    async def holder(self, name: str) -> str | None:
        value = await self._client.get(f"{self._key_prefix}{name}")
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        result: str = value
        return result


def make_redis_lock(client: Redis, key_prefix: str = "augur.lock.") -> RedisLock:
    """Construct a `RedisLock` bound to *client*.

    Kept separate from the constructor so tests can thread the same
    fakeredis instance into both the bus and the lock without tripping
    protocol-variance checks.
    """
    if client is None:
        raise LockError("RedisLock requires an explicit redis client")
    return RedisLock(client=client, key_prefix=key_prefix)
