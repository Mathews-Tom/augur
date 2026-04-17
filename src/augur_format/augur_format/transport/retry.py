"""Exponential backoff for webhook delivery.

Parameters match phase-3 §6.4: 1 s initial, 60 s cap, 5 attempts.
The helper takes an awaitable factory (fresh awaitable per attempt)
and an injectable sleep so tests can avoid real-time delays.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeliveryBackoff:
    """Backoff schedule for webhook delivery."""

    initial_seconds: float = 1.0
    max_seconds: float = 60.0
    max_retries: int = 5


class DeliveryRetryExhaustedError(RuntimeError):
    """Raised when every delivery attempt fails."""

    def __init__(self, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"webhook retry exhausted after {attempts} attempts: {last_error!r}")
        self.attempts = attempts
        self.last_error = last_error


async def deliver_with_backoff[T](
    factory: Callable[[], Awaitable[T]],
    policy: DeliveryBackoff,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Invoke *factory* with exponential backoff."""
    delay = policy.initial_seconds
    last_error: BaseException | None = None
    for attempt in range(1, policy.max_retries + 1):
        try:
            return await factory()
        except Exception as err:
            last_error = err
            if attempt == policy.max_retries:
                break
            await sleep(delay)
            delay = min(delay * 2.0, policy.max_seconds)
    if last_error is None:  # pragma: no cover
        raise RuntimeError("delivery retry loop exited without capturing an error")
    raise DeliveryRetryExhaustedError(attempts=policy.max_retries, last_error=last_error)
