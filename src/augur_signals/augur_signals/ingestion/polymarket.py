"""Polymarket REST poller.

Implements AbstractPoller against Polymarket's public REST endpoints.
Uses a shared aiohttp.ClientSession and the workspace backoff policy
for transient failures. Field names here are Polymarket-specific; the
normalizer maps them to the canonical MarketSnapshot shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiohttp

from augur_signals.ingestion.base import (
    RawMarketData,
    RawOrderBook,
    RawTrade,
)
from augur_signals.ingestion.retry import BackoffPolicy, with_backoff


class PolymarketPoller:
    """Concrete poller for Polymarket."""

    platform: str = "polymarket"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = "https://clob.polymarket.com",
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._backoff = backoff or BackoffPolicy()

    async def _get(self, path: str) -> dict[str, Any]:
        async def _call() -> dict[str, Any]:
            async with self._session.get(f"{self._base_url}{path}") as resp:
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json()
                return data

        return await with_backoff(_call, self._backoff)

    async def poll_markets(self) -> list[RawMarketData]:
        payload = await self._get("/markets")
        now = datetime.now(tz=UTC)
        markets = payload.get("data", payload.get("markets", []))
        return [
            RawMarketData(
                market_id=str(item["condition_id"]),
                platform=self.platform,
                fetched_at=now,
                payload=item,
            )
            for item in markets
        ]

    async def poll_orderbook(self, market_id: str) -> RawOrderBook | None:
        try:
            payload = await self._get(f"/book?market={market_id}")
        except Exception:
            return None
        bids = [(float(p), float(s)) for p, s in payload.get("bids", [])]
        asks = [(float(p), float(s)) for p, s in payload.get("asks", [])]
        return RawOrderBook(
            market_id=market_id,
            platform=self.platform,
            fetched_at=datetime.now(tz=UTC),
            bids=bids,
            asks=asks,
        )

    async def poll_trades(self, market_id: str, since: datetime) -> list[RawTrade]:
        since_iso = since.isoformat().replace("+00:00", "Z")
        payload = await self._get(f"/trades?market={market_id}&after={since_iso}")
        trades = payload.get("trades", [])
        return [
            RawTrade(
                market_id=market_id,
                platform=self.platform,
                timestamp=datetime.fromisoformat(str(t["timestamp"]).replace("Z", "+00:00")),
                price=float(t["price"]),
                size=float(t["size"]),
                side=str(t["side"]),
                counterparty=t.get("counterparty"),
            )
            for t in trades
        ]
