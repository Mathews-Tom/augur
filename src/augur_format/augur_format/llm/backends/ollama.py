"""Ollama backend adapter.

Uses plain httpx against the local Ollama daemon (default
``http://localhost:11434``) so the adapter has no hard dependency on
the ``ollama`` Python client. The adapter retries twice on connection
failures; local daemon outages should surface quickly, not retry for
a minute.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from augur_format.llm.backends.base import (
    AbstractLLMBackend,
    BackendError,
    CompletionResult,
)


class OllamaBackend(AbstractLLMBackend):
    """AbstractLLMBackend implementation routed through the local daemon."""

    backend_id: str = "ollama"

    def __init__(
        self,
        client: httpx.AsyncClient,
        endpoint: str = "http://localhost:11434",
        model: str = "gemma2:27b",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self._client = client
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max(1, max_retries)

    def model_id(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        try:
            response = await self._client.get(f"{self._endpoint}/api/tags", timeout=self._timeout)
        except Exception:
            return False
        return response.status_code == 200

    async def complete(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": self._model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        last_error: BaseException | None = None
        for _ in range(self._max_retries):
            started = time.perf_counter()
            try:
                response = await self._client.post(
                    f"{self._endpoint}/api/generate",
                    json=payload,
                    timeout=self._timeout,
                )
            except Exception as err:
                last_error = err
                continue
            if response.status_code != 200:
                status_error = BackendError(f"ollama returned status {response.status_code}")
                # 4xx indicates a malformed request from the adapter;
                # retrying will not recover. Surface the error
                # immediately so callers see the root cause.
                if 400 <= response.status_code < 500:
                    raise status_error
                last_error = status_error
                continue
            data: dict[str, Any] = response.json()
            duration_ms = int((time.perf_counter() - started) * 1000)
            return CompletionResult(
                text=str(data.get("response", "")),
                input_tokens=int(data.get("prompt_eval_count", 0)),
                output_tokens=int(data.get("eval_count", 0)),
                duration_ms=duration_ms,
            )
        raise BackendError(
            f"ollama completion failed after {self._max_retries} attempts: {last_error!r}"
        )
