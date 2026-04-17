"""NATS JetStream adapter for the EventBus protocol.

The adapter treats one JetStream stream as the transport for every
Augur subject. Producers publish via `js.publish`; consumers create
durable pull consumers keyed by `(subject_pattern, consumer_group)`
and pull messages in a bounded loop.

`nats-py` is imported lazily because `augur-signals` keeps it as
an optional dependency — a memory-backed deployment should not pull
the protobuf stack just to start. Unit tests inject a fake client via
`NATSBus(client=...)` so they exercise the adapter without a live
JetStream cluster.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from augur_signals.bus._config import NATSBody
from augur_signals.bus._lock import DistributedLock, LockError
from augur_signals.bus.base import BusError, BusMessage, EventBus

if TYPE_CHECKING:
    from nats.aio.client import Client as NATSClient


class NATSBus(EventBus):
    """EventBus backed by NATS JetStream.

    Attributes:
        config: Validated `NATSBody` loaded from `config/bus.toml`.
    """

    def __init__(self, config: NATSBody, *, client: NATSClient | None = None) -> None:
        self.config = config
        self._client = client
        self._js: Any | None = None
        self._connected = self._client is not None

    async def connect(self) -> None:
        if self._connected and self._js is not None:
            return
        if self._client is None:
            import nats

            self._client = await nats.connect(servers=list(self.config.servers))
        self._js = self._client.jetstream()
        await self._js.add_stream(
            name=self.config.stream_name,
            subjects=[f"{self.config.subject_prefix}.>"],
            num_replicas=self.config.replication_factor,
        )
        self._connected = True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.drain()
        self._connected = False

    async def publish(self, message: BusMessage) -> None:
        if self._js is None:
            raise BusError("NATSBus.connect() must be called before publish()")
        headers = message.headers or None
        await self._js.publish(message.subject, message.payload, headers=headers)

    async def subscribe(
        self, subject_pattern: str, consumer_group: str
    ) -> AsyncIterator[BusMessage]:
        if self._js is None:
            raise BusError("NATSBus.connect() must be called before subscribe()")
        sub = await self._js.pull_subscribe(subject_pattern, durable=consumer_group)
        import asyncio as _asyncio

        try:
            while True:
                msgs = await sub.fetch(batch=1, timeout=1)
                if not msgs:
                    # Yield control so an outer cancellation or break can
                    # observe the generator between empty-fetch polls.
                    await _asyncio.sleep(0)
                    continue
                for msg in msgs:
                    yield BusMessage(
                        subject=msg.subject,
                        payload=msg.data,
                        headers=dict(msg.headers) if msg.headers else None,
                    )
                    await msg.ack()
        finally:
            await sub.unsubscribe()


class NATSKVLock(DistributedLock):
    """Distributed lock backed by a NATS JetStream KV bucket."""

    def __init__(self, bucket_name: str, *, client: NATSClient | None = None) -> None:
        self._bucket_name = bucket_name
        self._client = client
        self._kv: Any | None = None

    async def connect(self) -> None:
        if self._client is None:
            import nats

            self._client = await nats.connect()
        js = self._client.jetstream()
        self._kv = await js.create_key_value(bucket=self._bucket_name)

    async def acquire(self, name: str, holder_id: str, ttl_seconds: int) -> bool:
        _ = ttl_seconds  # TTL is configured on the bucket at create_key_value time.
        if self._kv is None:
            raise LockError("NATSKVLock.connect() must be called before acquire()")
        try:
            await self._kv.create(name, holder_id.encode("utf-8"))
        except Exception:
            return False
        return True

    async def renew(self, name: str, holder_id: str, ttl_seconds: int) -> bool:
        _ = ttl_seconds
        if self._kv is None:
            raise LockError("NATSKVLock.connect() must be called before renew()")
        entry = await self._kv.get(name)
        if entry is None or entry.value.decode("utf-8") != holder_id:
            return False
        await self._kv.put(name, holder_id.encode("utf-8"))
        return True

    async def release(self, name: str, holder_id: str) -> None:
        if self._kv is None:
            raise LockError("NATSKVLock.connect() must be called before release()")
        entry = await self._kv.get(name)
        if entry is None or entry.value.decode("utf-8") != holder_id:
            return
        await self._kv.delete(name)

    async def holder(self, name: str) -> str | None:
        if self._kv is None:
            raise LockError("NATSKVLock.connect() must be called before holder()")
        entry = await self._kv.get(name)
        if entry is None:
            return None
        value: str = entry.value.decode("utf-8")
        return value
