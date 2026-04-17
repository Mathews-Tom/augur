"""Exponential backoff helpers for platform HTTP calls.

Parameters mirror the defaults in
docs/architecture/adaptive-polling-spec.md §Backoff Policy: initial
delay 1 s, cap 60 s, max 5 retries. Callers pass an awaitable factory;
each retry recreates the awaitable so timeouts and socket state are
not reused after a failure.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

RetryableFactory = Callable[[], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """Immutable backoff schedule."""

    initial_seconds: float = 1.0
    max_seconds: float = 60.0
    max_retries: int = 5


class RetryExhaustedError(RuntimeError):
    """Raised when every retry attempt fails; wraps the last exception."""

    def __init__(self, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"retry exhausted after {attempts} attempts: {last_error!r}")
        self.attempts = attempts
        self.last_error = last_error


async def with_backoff[T](
    factory: Callable[[], Awaitable[T]],
    policy: BackoffPolicy,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Invoke *factory* with exponential backoff on exception.

    Args:
        factory: Zero-arg callable returning a fresh awaitable each
            call. A fresh awaitable is required because an awaited
            coroutine cannot be awaited again.
        policy: Backoff schedule.
        sleep: Coroutine used to wait between attempts; overridable in
            tests to avoid real-time delays.

    Returns:
        The factory's eventual return value.

    Raises:
        RetryExhaustedError: Every attempt up to ``policy.max_retries``
            has failed. The last exception is attached.
    """
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
    if last_error is None:  # pragma: no cover — unreachable
        raise RuntimeError("retry loop exited without capturing an error")
    raise RetryExhaustedError(attempts=policy.max_retries, last_error=last_error)
