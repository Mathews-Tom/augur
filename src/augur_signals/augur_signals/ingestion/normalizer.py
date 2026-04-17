"""Raw platform data -> canonical MarketSnapshot.

Every platform's quirks are absorbed here; downstream consumers see the
same shape regardless of source. The normalizer is a pure function of
(RawMarketData, optional_orderbook) and raises on malformed payloads
rather than coercing missing fields. Verbatim fields (question,
resolution_criteria, resolution_source) are preserved exactly as
received.
"""

from __future__ import annotations

from datetime import datetime

from augur_signals.ingestion.base import RawMarketData, RawOrderBook
from augur_signals.models import MarketSnapshot


class MalformedPayloadError(ValueError):
    """Raised when a raw payload cannot be mapped onto MarketSnapshot."""


def _get(data: dict[str, object], *keys: str) -> object:
    """Return the first non-None value among *keys* in *data*."""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    raise MalformedPayloadError(f"missing required keys {keys} in payload")


def _maybe_float(data: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        if key in data and data[key] is not None:
            return float(data[key])  # type: ignore[arg-type]
    return None


def _maybe_datetime(data: dict[str, object], *keys: str) -> datetime | None:
    for key in keys:
        if key in data and data[key] is not None:
            value = data[key]
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _total_depth(book: RawOrderBook | None, side: str) -> float:
    if book is None:
        return 0.0
    levels = book.bids if side == "bid" else book.asks
    return sum(price * size for price, size in levels[:5])


def normalize(
    raw: RawMarketData,
    orderbook: RawOrderBook | None,
) -> MarketSnapshot:
    """Build a MarketSnapshot from a raw payload plus optional order book."""
    payload = raw.payload
    last_price = float(
        _get(payload, "last_price", "yes_price", "lastTradePrice")  # type: ignore[arg-type]
    )
    bid = _maybe_float(payload, "bid", "best_bid", "yes_bid")
    ask = _maybe_float(payload, "ask", "best_ask", "yes_ask")
    spread = None if bid is None or ask is None else ask - bid
    volume_24h = float(
        _get(payload, "volume_24h", "volume24Hr", "volume_24hr")  # type: ignore[arg-type]
    )
    liquidity = _total_depth(orderbook, "bid") + _total_depth(orderbook, "ask")
    question = str(_get(payload, "question", "title"))
    resolution_source = payload.get("resolution_source") or payload.get("rulesSource")
    resolution_criteria = payload.get("resolution_criteria") or payload.get("rules")
    closes_at = _maybe_datetime(payload, "closes_at", "close_time", "endDate")
    return MarketSnapshot(
        market_id=raw.market_id,
        platform=raw.platform,  # type: ignore[arg-type]
        timestamp=raw.fetched_at,
        last_price=last_price,
        bid=bid,
        ask=ask,
        spread=spread,
        volume_24h=volume_24h,
        liquidity=liquidity,
        question=question,
        resolution_source=str(resolution_source) if resolution_source else None,
        resolution_criteria=str(resolution_criteria) if resolution_criteria else None,
        closes_at=closes_at,
        raw_json=payload,
    )
