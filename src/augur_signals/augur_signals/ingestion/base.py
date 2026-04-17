"""Platform-agnostic polling protocol and raw-data DTOs.

The engine dispatches to concrete pollers (Polymarket, Kalshi)
through this protocol so the upstream pipeline sees a single shape
regardless of platform. All platform-specific field mapping stays in
the poller; the normalizer consumes the typed DTOs and produces the
canonical MarketSnapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RawMarketData:
    """Platform-specific market response held verbatim for replay."""

    market_id: str
    platform: str
    fetched_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawOrderBook:
    """Top-of-book depth snapshot used by feature computation and manipulation."""

    market_id: str
    platform: str
    fetched_at: datetime
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class RawTrade:
    """A single executed trade event used by manipulation signature checks."""

    market_id: str
    platform: str
    timestamp: datetime
    price: float
    size: float
    side: str
    counterparty: str | None = None


class AbstractPoller(Protocol):
    """Protocol every platform poller implements."""

    platform: str

    async def poll_markets(self) -> list[RawMarketData]:
        """Return the current market set for this platform."""
        ...

    async def poll_orderbook(self, market_id: str) -> RawOrderBook | None:
        """Return the current order book for *market_id*, or None on 404."""
        ...

    async def poll_trades(self, market_id: str, since: datetime) -> list[RawTrade]:
        """Return trades for *market_id* strictly newer than *since*."""
        ...
