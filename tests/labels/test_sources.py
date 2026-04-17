"""Tests for source adapter construction, auth requirements, and HTTP retry."""

from __future__ import annotations

import pytest

from augur_labels.sources._http import (
    HttpBackoff,
    HttpRetryExhaustedError,
    request_with_backoff,
)
from augur_labels.sources.ap import ApAdapter
from augur_labels.sources.bloomberg import BloombergAdapter
from augur_labels.sources.ft import FtAdapter
from augur_labels.sources.reuters import ReutersAdapter


@pytest.mark.unit
async def test_request_with_backoff_returns_on_success() -> None:
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    async def fake_sleep(_: float) -> None:
        return None

    result = await request_with_backoff(
        factory, HttpBackoff(max_retries=3), sleep=fake_sleep
    )
    assert result == "ok"
    assert calls == 1


@pytest.mark.unit
async def test_request_with_backoff_raises_on_exhaustion() -> None:
    async def factory() -> str:
        raise ConnectionError("always")

    async def fake_sleep(_: float) -> None:
        return None

    with pytest.raises(HttpRetryExhaustedError) as excinfo:
        await request_with_backoff(
            factory, HttpBackoff(initial_seconds=0.0, max_retries=3), sleep=fake_sleep
        )
    assert excinfo.value.attempts == 3


@pytest.mark.unit
def test_reuters_adapter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.delenv("REUTERS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="REUTERS_API_KEY"):
        ReutersAdapter(httpx.AsyncClient())


@pytest.mark.unit
def test_bloomberg_adapter_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.delenv("BLOOMBERG_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLOOMBERG_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="BLOOMBERG"):
        BloombergAdapter(httpx.AsyncClient())


@pytest.mark.unit
def test_ap_adapter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.delenv("AP_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AP_API_KEY"):
        ApAdapter(httpx.AsyncClient())


@pytest.mark.unit
async def test_ft_adapter_returns_empty_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from datetime import UTC, datetime

    monkeypatch.delenv("FT_API_KEY", raising=False)
    adapter = FtAdapter(httpx.AsyncClient())
    pubs = await adapter.fetch_recent(datetime(2026, 3, 1, tzinfo=UTC))
    assert pubs == []
    assert await adapter.health_check() is False
