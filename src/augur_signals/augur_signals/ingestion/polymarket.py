"""Polymarket REST poller.

Implements AbstractPoller against Polymarket's public REST endpoints.
Uses a shared aiohttp.ClientSession and the workspace backoff policy
for transient failures. Field names here are Polymarket-specific; the
normalizer maps them to the canonical MarketSnapshot shape.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote

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
        gamma_base_url: str = "https://gamma-api.polymarket.com",
        data_base_url: str = "https://data-api.polymarket.com",
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._gamma_base_url = gamma_base_url.rstrip("/")
        self._data_base_url = data_base_url.rstrip("/")
        self._backoff = backoff or BackoffPolicy()

    async def _get(self, base_url: str, path: str) -> Any:
        async def _call() -> Any:
            async with self._session.get(f"{base_url}{path}") as resp:
                resp.raise_for_status()
                return await resp.json()

        return await with_backoff(_call, self._backoff)

    async def poll_markets(self) -> list[RawMarketData]:
        payload = await self._get(self._base_url, "/markets")
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

    async def poll_market(self, condition_id: str) -> RawMarketData:
        encoded = quote(condition_id, safe="")
        payload = await self._get(self._gamma_base_url, f"/markets?condition_ids={encoded}")
        if not isinstance(payload, list) or not payload:
            raise LookupError(f"polymarket condition {condition_id!r} was not returned by Gamma")
        item = cast(dict[str, Any], payload[0])
        if str(item.get("conditionId")) != condition_id:
            raise LookupError(
                f"polymarket condition {condition_id!r} returned mismatched Gamma payload"
            )
        return RawMarketData(
            market_id=condition_id,
            platform=self.platform,
            fetched_at=datetime.now(tz=UTC),
            payload=_normalize_gamma_market_payload(item),
        )

    async def poll_orderbook(self, market_id: str) -> RawOrderBook | None:
        try:
            payload = await self._get(self._base_url, f"/book?token_id={quote(market_id, safe='')}")
        except aiohttp.ClientResponseError as exc:
            if exc.status != 404:
                raise
            return None
        bids = [_book_level(level) for level in payload.get("bids", [])]
        asks = [_book_level(level) for level in payload.get("asks", [])]
        return RawOrderBook(
            market_id=market_id,
            platform=self.platform,
            fetched_at=datetime.now(tz=UTC),
            bids=bids,
            asks=asks,
        )

    async def poll_trades(self, market_id: str, since: datetime) -> list[RawTrade]:
        payload = await self._get(
            self._data_base_url,
            f"/trades?market={quote(market_id, safe='')}",
        )
        trades = payload if isinstance(payload, list) else payload.get("trades", [])
        return [
            RawTrade(
                market_id=market_id,
                platform=self.platform,
                timestamp=_trade_timestamp(t["timestamp"]),
                price=float(t["price"]),
                size=float(t["size"]),
                side=str(t["side"]).lower(),
                counterparty=t.get("proxyWallet") or t.get("counterparty"),
            )
            for t in trades
            if _trade_timestamp(t["timestamp"]) > since
        ]


def _normalize_gamma_market_payload(item: dict[str, Any]) -> dict[str, Any]:
    condition_id = str(item["conditionId"])
    outcome_prices = _json_list(item.get("outcomePrices"))
    if outcome_prices:
        yes_price = _required_float(outcome_prices[0])
    else:
        yes_price = _required_float(item["lastTradePrice"])
    return {
        **item,
        "condition_id": condition_id,
        "last_price": yes_price,
        "volume_24h": float(item.get("volume24hrClob") or item.get("volume24hr") or 0.0),
        "bid": _maybe_float(item.get("bestBid")),
        "ask": _maybe_float(item.get("bestAsk")),
        "question": str(item["question"]),
        "rules": item.get("description"),
        "rulesSource": item.get("resolutionSource"),
        "endDate": item.get("endDate") or item.get("endDateIso"),
        "clob_token_ids": _json_list(item.get("clobTokenIds")),
    }


def primary_clob_token_id(raw: RawMarketData) -> str:
    token_ids = raw.payload.get("clob_token_ids")
    if not isinstance(token_ids, list) or not token_ids:
        raise ValueError(f"polymarket market {raw.market_id!r} has no CLOB token ids")
    return str(token_ids[0])


def _json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    return []


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    return _required_float(value)


def _required_float(value: object) -> float:
    if isinstance(value, (str, int, float)):
        return float(value)
    raise TypeError(f"expected numeric value, got {type(value).__name__}")


def _book_level(level: object) -> tuple[float, float]:
    if isinstance(level, dict):
        return _required_float(level["price"]), _required_float(level["size"])
    if isinstance(level, (list, tuple)) and len(level) == 2:
        return _required_float(level[0]), _required_float(level[1])
    raise TypeError(f"invalid Polymarket book level: {level!r}")


def _trade_timestamp(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
