"""Tests for the webhook adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from augur_format._config import WebhookConfig
from augur_format.transport.retry import (
    DeliveryBackoff,
    DeliveryRetryExhaustedError,
    deliver_with_backoff,
)
from augur_format.transport.webhook import (
    WebhookFormatter,
    WebhookTarget,
)
from augur_signals.models import (
    InterpretationMode,
    MarketSignal,
    SignalContext,
    SignalType,
    new_signal_id,
)


def _context() -> SignalContext:
    signal = MarketSignal(
        signal_id=new_signal_id(),
        market_id="kalshi_fed",
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.8,
        direction=1,
        confidence=0.7,
        fdr_adjusted=True,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        raw_features={"calibration_provenance": "d@identity_v0"},
    )
    return SignalContext(
        signal=signal,
        market_question="Will the Fed raise rates?",
        resolution_criteria="YES if rate rises.",
        resolution_source="Federal Reserve",
        closes_at=datetime(2026, 6, 15, tzinfo=UTC),
        related_markets=[],
        investigation_prompts=["Check FOMC calendar."],
        interpretation_mode=InterpretationMode.DETERMINISTIC,
    )


@pytest.mark.unit
async def test_retry_exhaustion_raises() -> None:
    async def failing() -> None:
        raise ConnectionError("no route")

    async def fake_sleep(_: float) -> None:
        return None

    with pytest.raises(DeliveryRetryExhaustedError) as excinfo:
        await deliver_with_backoff(
            failing, DeliveryBackoff(initial_seconds=0.0, max_retries=3), sleep=fake_sleep
        )
    assert excinfo.value.attempts == 3


@pytest.mark.unit
async def test_delivery_succeeds_on_2xx() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "body": request.content})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        formatter = WebhookFormatter(client, WebhookConfig())
        target = WebhookTarget(
            target_id="t1",
            url="https://hooks.example.com/augur",  # type: ignore[arg-type]
            format="json",
        )
        result = await formatter.deliver(_context(), target)
    assert result.delivered
    assert result.status_code == 200
    assert len(calls) == 1


@pytest.mark.unit
async def test_delivery_fails_on_5xx_after_retries() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        formatter = WebhookFormatter(
            client,
            WebhookConfig(
                initial_retry_delay_seconds=0.001,
                max_retry_delay_seconds=0.001,
                max_retries=3,
            ),
        )
        target = WebhookTarget(
            target_id="t1",
            url="https://hooks.example.com/augur",  # type: ignore[arg-type]
            format="json",
        )
        result = await formatter.deliver(_context(), target)
    assert not result.delivered
    assert count["n"] == 3


@pytest.mark.unit
async def test_delivery_drops_on_4xx() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return httpx.Response(400)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        formatter = WebhookFormatter(client, WebhookConfig(max_retries=3))
        target = WebhookTarget(
            target_id="t1",
            url="https://hooks.example.com/augur",  # type: ignore[arg-type]
            format="json",
        )
        result = await formatter.deliver(_context(), target)
    assert not result.delivered
    assert count["n"] == 1  # no retry on 4xx
    assert result.status_code == 400


@pytest.mark.unit
async def test_slack_blocks_format_is_valid_block_kit() -> None:
    captured: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        formatter = WebhookFormatter(client, WebhookConfig())
        target = WebhookTarget(
            target_id="slack",
            url="https://hooks.slack.com/services/TEST",  # type: ignore[arg-type]
            format="slack_blocks",
        )
        result = await formatter.deliver(_context(), target)
    assert result.delivered
    payload = json.loads(captured[0])
    assert "blocks" in payload
    assert any(b["type"] == "header" for b in payload["blocks"])
    # Confidence should be formatted to two decimals in header text.
    header = next(b for b in payload["blocks"] if b["type"] == "header")
    assert "0.70" in header["text"]["text"]


@pytest.mark.unit
async def test_auth_header_from_env_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(dict(request.headers))
        return httpx.Response(200)

    monkeypatch.setenv("AUGUR_TEST_WEBHOOK_AUTH", "Bearer secret-xyz")
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        formatter = WebhookFormatter(client, WebhookConfig())
        target = WebhookTarget(
            target_id="t1",
            url="https://hooks.example.com/augur",  # type: ignore[arg-type]
            format="json",
            auth_header_env="AUGUR_TEST_WEBHOOK_AUTH",
        )
        await formatter.deliver(_context(), target)
    assert captured[0].get("authorization") == "Bearer secret-xyz"
