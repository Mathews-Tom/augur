"""Tests for ingestion DTOs, retry policy, and the normalizer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from augur_signals.ingestion.base import RawMarketData, RawOrderBook
from augur_signals.ingestion.normalizer import MalformedPayloadError, normalize
from augur_signals.ingestion.polymarket import (
    _normalize_gamma_market_payload,
    primary_clob_token_id,
)
from augur_signals.ingestion.retry import (
    BackoffPolicy,
    RetryExhaustedError,
    with_backoff,
)


@pytest.mark.unit
async def test_with_backoff_returns_on_success() -> None:
    calls: list[int] = []

    async def factory() -> str:
        calls.append(1)
        return "ok"

    async def fake_sleep(_: float) -> None:
        return None

    result = await with_backoff(factory, BackoffPolicy(max_retries=3), sleep=fake_sleep)
    assert result == "ok"
    assert len(calls) == 1


@pytest.mark.unit
async def test_with_backoff_retries_transient_failures() -> None:
    attempts: list[int] = []

    async def factory() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("transient")
        return "recovered"

    async def fake_sleep(_: float) -> None:
        return None

    policy = BackoffPolicy(initial_seconds=0.0, max_seconds=0.0, max_retries=5)
    result = await with_backoff(factory, policy, sleep=fake_sleep)
    assert result == "recovered"
    assert len(attempts) == 3


@pytest.mark.unit
async def test_with_backoff_raises_retry_exhausted() -> None:
    async def factory() -> str:
        raise ConnectionError("always fails")

    async def fake_sleep(_: float) -> None:
        return None

    policy = BackoffPolicy(initial_seconds=0.0, max_retries=3)
    with pytest.raises(RetryExhaustedError) as excinfo:
        await with_backoff(factory, policy, sleep=fake_sleep)
    assert excinfo.value.attempts == 3
    assert isinstance(excinfo.value.last_error, ConnectionError)


@pytest.mark.unit
def test_normalize_polymarket_payload() -> None:
    raw = RawMarketData(
        market_id="0xdead",
        platform="polymarket",
        fetched_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        payload={
            "last_price": 0.55,
            "best_bid": 0.54,
            "best_ask": 0.56,
            "volume24Hr": 100000.0,
            "question": "Will X happen?",
            "resolution_source": "Reuters",
            "rules": "Resolves YES if X happens.",
            "endDate": "2026-06-15T18:00:00Z",
        },
    )
    book = RawOrderBook(
        market_id="0xdead",
        platform="polymarket",
        fetched_at=raw.fetched_at,
        bids=[(0.54, 1000.0)],
        asks=[(0.56, 1000.0)],
    )
    snap = normalize(raw, book)
    assert snap.market_id == "0xdead"
    assert snap.platform == "polymarket"
    assert snap.last_price == 0.55
    assert snap.spread == pytest.approx(0.02)
    assert snap.volume_24h == 100000.0
    assert snap.liquidity == pytest.approx(0.54 * 1000 + 0.56 * 1000)
    assert snap.closes_at == datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


@pytest.mark.unit
def test_polymarket_gamma_payload_maps_to_normalizer_contract() -> None:
    payload = _normalize_gamma_market_payload(
        {
            "conditionId": "0xabc",
            "question": "Will X happen?",
            "description": "Resolves YES if X happens.",
            "resolutionSource": "Source text",
            "outcomePrices": '["0.42", "0.58"]',
            "volume24hr": 123.0,
            "bestBid": "0.41",
            "bestAsk": "0.43",
            "endDate": "2026-06-15T18:00:00Z",
            "clobTokenIds": '["yes-token", "no-token"]',
        }
    )
    raw = RawMarketData(
        market_id="0xabc",
        platform="polymarket",
        fetched_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        payload=payload,
    )

    snap = normalize(raw, None)

    assert snap.last_price == 0.42
    assert snap.bid == 0.41
    assert snap.ask == 0.43
    assert snap.volume_24h == 123.0
    assert snap.resolution_source == "Source text"
    assert primary_clob_token_id(raw) == "yes-token"


@pytest.mark.unit
def test_normalize_kalshi_payload() -> None:
    raw = RawMarketData(
        market_id="FED-RATE-JUN26",
        platform="kalshi",
        fetched_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        payload={
            "yes_price": 0.30,
            "yes_bid": 0.29,
            "yes_ask": 0.31,
            "volume_24h": 50000.0,
            "title": "Will the Fed raise rates in June 2026?",
            "rulesSource": "Federal Reserve press release",
            "resolution_criteria": "YES if rate range rises.",
            "close_time": "2026-06-15T18:00:00Z",
        },
    )
    snap = normalize(raw, None)
    assert snap.platform == "kalshi"
    assert snap.last_price == 0.30
    assert snap.liquidity == 0.0  # no order book
    assert snap.question.startswith("Will the Fed")


@pytest.mark.unit
def test_normalize_rejects_missing_price() -> None:
    raw = RawMarketData(
        market_id="m",
        platform="kalshi",
        fetched_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        payload={"volume_24h": 1000.0, "question": "q"},
    )
    with pytest.raises(MalformedPayloadError):
        normalize(raw, None)
