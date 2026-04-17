"""Kalshi REST poller.

Implements AbstractPoller against Kalshi's authenticated REST API. The
API key is read from the KALSHI_API_KEY environment variable; missing
credentials fail loud at construction time rather than at first call.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import aiohttp

from augur_signals.ingestion.base import (
    RawMarketData,
    RawOrderBook,
    RawTrade,
)
from augur_signals.ingestion.retry import BackoffPolicy, with_backoff


class KalshiPoller:
    """Concrete poller for Kalshi."""

    platform: str = "kalshi"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str = "https://trading-api.kalshi.com/v2",
        api_key: str | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        key = api_key or os.environ.get("KALSHI_API_KEY")
        if not key:
            raise RuntimeError("KalshiPoller requires KALSHI_API_KEY environment variable")
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_key = key
        self._backoff = backoff or BackoffPolicy()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _get(self, path: str) -> dict[str, Any]:
        async def _call() -> dict[str, Any]:
            async with self._session.get(
                f"{self._base_url}{path}", headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json()
                return data

        return await with_backoff(_call, self._backoff)

    async def poll_markets(self) -> list[RawMarketData]:
        payload = await self._get("/markets")
        now = datetime.now(tz=UTC)
        markets = payload.get("markets", [])
        return [
            RawMarketData(
                market_id=str(item["ticker"]),
                platform=self.platform,
                fetched_at=now,
                payload=item,
            )
            for item in markets
        ]

    async def poll_orderbook(self, market_id: str) -> RawOrderBook | None:
        try:
            payload = await self._get(f"/markets/{market_id}/orderbook")
        except Exception:
            return None
        book = payload.get("orderbook", {})
        bids = [(float(p), float(s)) for p, s in book.get("yes", [])]
        asks = [(float(p), float(s)) for p, s in book.get("no", [])]
        return RawOrderBook(
            market_id=market_id,
            platform=self.platform,
            fetched_at=datetime.now(tz=UTC),
            bids=bids,
            asks=asks,
        )

    async def poll_trades(self, market_id: str, since: datetime) -> list[RawTrade]:
        since_iso = since.isoformat().replace("+00:00", "Z")
        payload = await self._get(f"/markets/{market_id}/trades?min_ts={since_iso}")
        trades = payload.get("trades", [])
        return [
            RawTrade(
                market_id=market_id,
                platform=self.platform,
                timestamp=datetime.fromisoformat(str(t["created_time"]).replace("Z", "+00:00")),
                price=float(t["yes_price"]),
                size=float(t["count"]),
                side=str(t["taker_side"]),
                counterparty=None,
            )
            for t in trades
        ]
