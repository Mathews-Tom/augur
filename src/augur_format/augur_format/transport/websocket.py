"""WebSocket transport with structured frames.

Frame types mirror phase-3 §7: SIGNAL payloads carry the canonical
SignalContext JSON; HEARTBEAT frames arrive at the configured
interval; STORM_START and STORM_END signal the dedup layer's storm
transitions. Broadcast is fan-out across connected clients with a
per-connection bounded queue; slow clients are dropped rather than
stalling the broadcast loop.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from augur_format.deterministic.json_feed import to_canonical_json
from augur_signals.models import SignalContext


class FrameType(StrEnum):
    """Closed frame-type enum for the WebSocket protocol."""

    SIGNAL = "signal"
    HEARTBEAT = "heartbeat"
    STORM_START = "storm_start"
    STORM_END = "storm_end"


@dataclass(frozen=True, slots=True)
class WebSocketFrame:
    """One message on the wire."""

    frame_type: FrameType
    frame_id: str
    ts: datetime
    payload: dict[str, Any] | None = None

    def to_json(self) -> bytes:
        body: dict[str, Any] = {
            "frame_type": self.frame_type.value,
            "frame_id": self.frame_id,
            "ts": self.ts.isoformat().replace("+00:00", "Z"),
        }
        if self.payload is not None:
            body["payload"] = self.payload
        return json.dumps(body, separators=(",", ":")).encode("utf-8")


def signal_frame(context: SignalContext, now: datetime) -> WebSocketFrame:
    """Build a SIGNAL frame whose payload is the canonical SignalContext JSON."""
    return WebSocketFrame(
        frame_type=FrameType.SIGNAL,
        frame_id=str(uuid4()),
        ts=now,
        payload=json.loads(to_canonical_json(context).decode("utf-8")),
    )


def heartbeat_frame(now: datetime) -> WebSocketFrame:
    return WebSocketFrame(frame_type=FrameType.HEARTBEAT, frame_id=str(uuid4()), ts=now)


def storm_start_frame(now: datetime) -> WebSocketFrame:
    return WebSocketFrame(frame_type=FrameType.STORM_START, frame_id=str(uuid4()), ts=now)


def storm_end_frame(now: datetime) -> WebSocketFrame:
    return WebSocketFrame(frame_type=FrameType.STORM_END, frame_id=str(uuid4()), ts=now)


@dataclass(slots=True)
class ClientSubscription:
    """One connected client's send queue and filter."""

    queue: asyncio.Queue[WebSocketFrame]
    consumer_type: str | None = None
    dropped: int = 0
    # Per-subscription lock so concurrent publishers serialise the
    # full-queue check-and-drop instead of each draining one slot.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WebSocketBroadcaster:
    """In-process broadcaster; adapts to a real websockets server easily.

    The broadcaster manages per-client queues. A `publish` call
    enqueues the frame for every subscriber whose consumer_type
    matches (or whose subscription is unfiltered). Queues are bounded
    by `per_connection_buffer`; enqueue on a full queue drops the
    oldest frame to preserve timeliness, matching the dedup/storm
    doc's rationale for LIFO under pressure.
    """

    def __init__(self, per_connection_buffer: int = 64) -> None:
        if per_connection_buffer <= 0:
            raise ValueError("per_connection_buffer must be positive")
        self._buffer = per_connection_buffer
        self._subscriptions: list[ClientSubscription] = []

    def subscribe(self, consumer_type: str | None = None) -> ClientSubscription:
        sub = ClientSubscription(
            queue=asyncio.Queue(maxsize=self._buffer),
            consumer_type=consumer_type,
        )
        self._subscriptions.append(sub)
        return sub

    def unsubscribe(self, subscription: ClientSubscription) -> None:
        if subscription in self._subscriptions:
            self._subscriptions.remove(subscription)

    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    async def publish(
        self,
        frame: WebSocketFrame,
        *,
        consumer_type_filter: Callable[[str | None], bool] | None = None,
    ) -> None:
        for sub in list(self._subscriptions):
            if consumer_type_filter is not None and not consumer_type_filter(sub.consumer_type):
                continue
            async with sub.lock:
                # Serialise check-and-drop so concurrent publishers do
                # not each drain a slot from the same full queue.
                if sub.queue.full():
                    try:
                        sub.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    sub.dropped += 1
                await sub.queue.put(frame)

    async def stream(self, subscription: ClientSubscription) -> AsyncIterator[WebSocketFrame]:
        """Yield frames queued for *subscription* until cancelled."""
        try:
            while True:
                yield await subscription.queue.get()
        finally:
            self.unsubscribe(subscription)


@dataclass(slots=True)
class HeartbeatScheduler:
    """Answers "should a heartbeat emit now?" against caller-supplied time.

    The scheduler is mutable by design — `record` tracks the last
    emission so `should_emit` can gate the next one. Engine code
    owns the outer loop and passes `now` explicitly so the scheduler
    stays backtest-deterministic.
    """

    interval_seconds: int = 30
    _last_sent: datetime | None = field(default=None)

    def should_emit(self, now: datetime) -> bool:
        if self._last_sent is None:
            return True
        return (now - self._last_sent).total_seconds() >= self.interval_seconds

    def record(self, now: datetime) -> None:
        self._last_sent = now
