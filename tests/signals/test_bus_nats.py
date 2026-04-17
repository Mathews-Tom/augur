"""Tests for the NATS JetStream EventBus adapter with a fake client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from augur_signals.bus._config import NATSBody
from augur_signals.bus.base import BusError, BusMessage
from augur_signals.bus.nats import NATSBus


@dataclass
class _FakeMsg:
    subject: str
    data: bytes
    headers: dict[str, str] | None = None
    _acked: bool = False

    async def ack(self) -> None:
        self._acked = True


@dataclass
class _FakeSub:
    stream_name: str
    subject_pattern: str
    durable: str
    backlog: list[_FakeMsg] = field(default_factory=list)
    cursor: int = 0
    unsubscribed: bool = False

    async def fetch(self, batch: int = 1, timeout: int = 1) -> list[_FakeMsg]:  # noqa: ASYNC109
        _ = timeout
        msgs: list[_FakeMsg] = []
        while self.cursor < len(self.backlog) and len(msgs) < batch:
            msgs.append(self.backlog[self.cursor])
            self.cursor += 1
        return msgs

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


@dataclass
class _FakeJetStream:
    stream_name_added: str | None = None
    subjects: list[str] = field(default_factory=list)
    published: list[_FakeMsg] = field(default_factory=list)
    subs: list[_FakeSub] = field(default_factory=list)

    async def add_stream(self, *, name: str, subjects: list[str], num_replicas: int) -> None:
        _ = num_replicas
        self.stream_name_added = name
        self.subjects = subjects

    async def publish(
        self, subject: str, payload: bytes, headers: dict[str, str] | None = None
    ) -> None:
        msg = _FakeMsg(subject=subject, data=payload, headers=headers)
        self.published.append(msg)
        for sub in self.subs:
            if self._matches(sub.subject_pattern, subject):
                sub.backlog.append(msg)

    async def pull_subscribe(self, subject_pattern: str, durable: str) -> _FakeSub:
        sub = _FakeSub(
            stream_name=self.stream_name_added or "",
            subject_pattern=subject_pattern,
            durable=durable,
        )
        # Seed the new subscription with any prior publishes that match;
        # real JetStream pull consumers deliver the stream from ID 1.
        for msg in self.published:
            if self._matches(subject_pattern, msg.subject):
                sub.backlog.append(msg)
        self.subs.append(sub)
        return sub

    @staticmethod
    def _matches(pattern: str, subject: str) -> bool:
        if pattern == subject:
            return True
        if pattern.endswith(".>"):
            return subject.startswith(pattern[:-1])
        return False


@dataclass
class _FakeClient:
    _js: _FakeJetStream = field(default_factory=_FakeJetStream)
    drained: bool = False

    def jetstream(self) -> _FakeJetStream:
        return self._js

    async def drain(self) -> None:
        self.drained = True


@pytest.fixture
def client() -> _FakeClient:
    return _FakeClient()


@pytest.mark.asyncio
async def test_nats_connect_declares_stream_with_subject_prefix(
    client: _FakeClient,
) -> None:
    config = NATSBody(servers=["nats://localhost:4222"], stream_name="augur")
    bus = NATSBus(config, client=client)  # type: ignore[arg-type]
    await bus.connect()
    assert client._js.stream_name_added == "augur"
    assert client._js.subjects == ["augur.>"]


@pytest.mark.asyncio
async def test_nats_publish_and_subscribe_roundtrip(client: _FakeClient) -> None:
    config = NATSBody()
    bus = NATSBus(config, client=client)  # type: ignore[arg-type]
    await bus.connect()

    subject = "augur.signals"
    await bus.publish(BusMessage(subject=subject, payload=b"hi"))
    await bus.publish(BusMessage(subject=subject, payload=b"there", headers={"k": "v"}))

    received: list[BusMessage] = []

    async def consume() -> None:
        async for msg in bus.subscribe("augur.signals", "dedup"):
            received.append(msg)
            if len(received) >= 2:
                break

    await asyncio.wait_for(consume(), timeout=1.0)
    assert [m.payload for m in received] == [b"hi", b"there"]
    assert received[1].headers == {"k": "v"}


@pytest.mark.asyncio
async def test_nats_publish_requires_connect_first(client: _FakeClient) -> None:
    config = NATSBody()
    bus = NATSBus(config, client=client)  # type: ignore[arg-type]
    with pytest.raises(BusError, match="connect"):
        await bus.publish(BusMessage(subject="augur.signals", payload=b"x"))


@pytest.mark.asyncio
async def test_nats_close_drains_client(client: _FakeClient) -> None:
    config = NATSBody()
    bus = NATSBus(config, client=client)  # type: ignore[arg-type]
    await bus.connect()
    await bus.close()
    assert client.drained is True


@pytest.mark.asyncio
async def test_nats_subscribe_acks_yielded_messages(client: _FakeClient) -> None:
    """Ack is deferred to the next iteration; break leaves the last
    yielded message un-acked for JetStream redelivery."""
    config = NATSBody()
    bus = NATSBus(config, client=client)  # type: ignore[arg-type]
    await bus.connect()
    await bus.publish(BusMessage(subject="augur.signals", payload=b"a"))
    await bus.publish(BusMessage(subject="augur.signals", payload=b"b"))
    await bus.publish(BusMessage(subject="augur.signals", payload=b"c"))

    count = 0
    async for _msg in bus.subscribe("augur.signals", "dedup"):
        count += 1
        if count >= 3:
            break

    acks = [m._acked for m in client._js.published]
    # msg-a acked at the iteration that yielded msg-b; msg-b acked at
    # the iteration that yielded msg-c; msg-c pending because the
    # consumer broke before the next iteration.
    assert acks == [True, True, False]
