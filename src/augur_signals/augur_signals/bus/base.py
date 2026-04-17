"""Generic subject-addressed async event bus protocol.

The Phase 1 InProcessAsyncBus in memory.py moves typed
MarketSignal objects and remains the monolith's transport. Phase 5
adds a separate byte-level protocol, EventBus, that workers use to
publish to and subscribe from named subjects. Serialization lives at
the worker boundary; the bus itself is agnostic.

Every adapter (NATS, Redis Streams, in-process for tests) implements
the same protocol so make_bus selects at startup and the workers
stay backend-agnostic. The subject naming scheme matches
`.docs/phase-5-scaling.md §4.3`:

* augur.snapshots.<platform>.<market_id>
* augur.features.<market_id>
* augur.candidates.<detector_id>
* augur.flagged_signals
* augur.calibrated_signals
* augur.signals
* augur.contexts
* augur.briefs.<format>
* augur.ops.events
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class BusMessage:
    """One envelope on the wire.

    Attributes:
        subject: Full subject the publisher routed to.
        payload: Raw body; producers serialize before publish and
            consumers deserialize after subscribe.
        headers: Optional small key/value metadata. NATS supports this
            natively; the Redis adapter encodes it as hash fields on
            the stream entry.
    """

    subject: str
    payload: bytes
    headers: dict[str, str] | None = None


@runtime_checkable
class EventBus(Protocol):
    """Byte-level pub/sub transport used by multi-process workers.

    Implementations are at-least-once: a consumer that crashes before
    acknowledging a message will see it redelivered on restart. Order
    is preserved per subject for a single subscriber; no global order
    guarantee.
    """

    async def connect(self) -> None:
        """Open connections, declare streams, and attach consumer groups."""
        ...

    async def close(self) -> None:
        """Flush pending publishes and close connections."""
        ...

    async def publish(self, message: BusMessage) -> None:
        """Publish *message* to its subject."""
        ...

    def subscribe(self, subject_pattern: str, consumer_group: str) -> AsyncIterator[BusMessage]:
        """Yield messages matching *subject_pattern* on *consumer_group*.

        The iterator is async and terminates when the bus closes
        or the caller cancels the underlying task. The adapter
        acknowledges each message after the consumer's async for
        body returns without raising.
        """
        ...


class BusError(RuntimeError):
    """Raised by adapter code when a bus operation fails terminally."""
