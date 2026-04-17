"""Tests for the LLM backend adapters (mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from augur_format.llm.backends.anthropic import AnthropicBackend
from augur_format.llm.backends.base import BackendError, CompletionResult
from augur_format.llm.backends.ollama import OllamaBackend


@pytest.mark.asyncio
async def test_ollama_health_check_passes_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        backend = OllamaBackend(client)
        assert await backend.health_check() is True


@pytest.mark.asyncio
async def test_ollama_complete_returns_parsed_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": "Hello world",
                "prompt_eval_count": 10,
                "eval_count": 3,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        backend = OllamaBackend(client, max_retries=1)
        result = await backend.complete("system", "prompt", max_tokens=32, temperature=0.2)
    assert isinstance(result, CompletionResult)
    assert result.text == "Hello world"
    assert result.input_tokens == 10
    assert result.output_tokens == 3


@pytest.mark.asyncio
async def test_ollama_raises_backenderror_on_exhaustion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        backend = OllamaBackend(client, max_retries=2)
        with pytest.raises(BackendError):
            await backend.complete("system", "prompt", max_tokens=32, temperature=0.2)


@pytest.mark.unit
def test_anthropic_requires_env_or_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(BackendError, match="ANTHROPIC_API_KEY"):
        AnthropicBackend()


@pytest.mark.asyncio
async def test_anthropic_accepts_injected_client_and_parses_text() -> None:
    class _FakeMessages:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def create(self, **kwargs: Any) -> SimpleNamespace:
            self.calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="ok")],
                usage=SimpleNamespace(input_tokens=5, output_tokens=2),
            )

    class _FakeClient:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    client = _FakeClient()
    backend = AnthropicBackend(client=client, max_retries=1)
    result = await backend.complete("system", "prompt", max_tokens=32, temperature=0.2)
    assert result.text == "ok"
    assert result.input_tokens == 5
    assert result.output_tokens == 2


@pytest.mark.asyncio
async def test_anthropic_exhausts_retries_and_raises_backenderror() -> None:
    class _AlwaysFail:
        async def create(self, **kwargs: Any) -> None:
            raise RuntimeError("transient")

    class _Client:
        def __init__(self) -> None:
            self.messages = _AlwaysFail()

    backend = AnthropicBackend(client=_Client(), max_retries=2)
    with pytest.raises(BackendError):
        await backend.complete("system", "prompt", max_tokens=32, temperature=0.2)
