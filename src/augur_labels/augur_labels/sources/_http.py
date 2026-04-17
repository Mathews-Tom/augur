"""Shared httpx client helpers with exponential backoff.

Every source adapter routes its calls through ``request_with_backoff``
so retry semantics stay consistent: 1 s initial delay, doubling to a
60 s cap, 5-retry max on any exception. The helper is parameterized
over the request factory so the session's headers, auth, and URL
remain caller-specific.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HttpBackoff:
    """Backoff schedule used by every source adapter."""

    initial_seconds: float = 1.0
    max_seconds: float = 60.0
    max_retries: int = 5


class HttpRetryExhaustedError(RuntimeError):
    """Raised when every adapter retry attempt fails."""

    def __init__(self, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"http retry exhausted after {attempts} attempts: {last_error!r}")
        self.attempts = attempts
        self.last_error = last_error


async def request_with_backoff[T](
    factory: Callable[[], Awaitable[T]],
    policy: HttpBackoff,
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
        raise RuntimeError("http retry loop exited without capturing an error")
    raise HttpRetryExhaustedError(attempts=policy.max_retries, last_error=last_error)
