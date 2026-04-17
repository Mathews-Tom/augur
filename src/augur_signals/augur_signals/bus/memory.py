"""In-process async signal bus.

A single-process bounded queue that fanouts to every subscriber. The
multi-process runtime swaps this for NATS or Redis Streams adapters
behind the same method surface.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from augur_signals.models import MarketSignal


class InProcessAsyncBus:
    """Bounded async queue with broadcast subscribe semantics."""

    def __init__(self, capacity: int = 256) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._subscribers: list[asyncio.Queue[MarketSignal]] = []

    async def publish(self, signal: MarketSignal) -> None:
        """Fan *signal* out to every current subscriber."""
        for queue in list(self._subscribers):
            if queue.qsize() >= self._capacity:
                # Apply LIFO drop under pressure per the storm doc.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await queue.put(signal)

    async def subscribe(self) -> AsyncIterator[MarketSignal]:
        """Register a subscriber; yield published signals until cancelled."""
        queue: asyncio.Queue[MarketSignal] = asyncio.Queue(maxsize=self._capacity)
        self._subscribers.append(queue)
        try:
            while True:
                signal = await queue.get()
                yield signal
        finally:
            self._subscribers.remove(queue)

    def queue_depth(self) -> int:
        """Maximum depth across all subscribers."""
        if not self._subscribers:
            return 0
        return max(q.qsize() for q in self._subscribers)

    def subscriber_count(self) -> int:
        return len(self._subscribers)
