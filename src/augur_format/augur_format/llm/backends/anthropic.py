"""Anthropic backend adapter.

Imports the anthropic SDK lazily via ``importlib.import_module`` so
that the llm-isolation test continues to assert anthropic is NOT
importable in the default environment. Operators install anthropic
via the ``augur-format[llm-cloud]`` extra before enabling the
backend.
"""

from __future__ import annotations

import importlib
import os
import time
from typing import Any

from augur_format.llm.backends.base import (
    AbstractLLMBackend,
    BackendError,
    CompletionResult,
)


class AnthropicBackend(AbstractLLMBackend):
    """AbstractLLMBackend implementation routed through the anthropic SDK."""

    backend_id: str = "anthropic"

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key_env: str = "ANTHROPIC_API_KEY",
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        client: Any | None = None,
    ) -> None:
        key = os.environ.get(api_key_env)
        if key is None and client is None:
            raise BackendError(
                f"AnthropicBackend requires {api_key_env} environment variable "
                "or an injected client"
            )
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max(1, max_retries)
        if client is None:
            # Lazy import so the module is safely loadable when the
            # anthropic extra is not installed; the adapter itself
            # only runs when the operator opts in.
            anthropic = importlib.import_module("anthropic")
            client = anthropic.AsyncAnthropic(api_key=key)
        self._client = client

    def model_id(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        # The SDK does not expose a cheap ping; surface True when the
        # client constructs successfully and let the first real
        # completion surface any runtime errors.
        return self._client is not None

    async def complete(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        last_error: BaseException | None = None
        for _ in range(self._max_retries):
            started = time.perf_counter()
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=self._timeout,
                )
            except Exception as err:
                # Narrow retry to transient failures. Authentication
                # and permission errors raise immediately so auth
                # failures do not burn the retry budget. The class
                # lookup is string-based so the module stays loadable
                # without the anthropic SDK installed.
                class_path = f"{type(err).__module__}.{type(err).__name__}"
                terminal = {
                    "anthropic.AuthenticationError",
                    "anthropic.PermissionDeniedError",
                    "anthropic.BadRequestError",
                }
                if class_path in terminal:
                    raise BackendError(f"anthropic terminal error: {err!r}") from err
                last_error = err
                continue
            duration_ms = int((time.perf_counter() - started) * 1000)
            content_blocks = getattr(response, "content", [])
            text_parts = [
                getattr(block, "text", "")
                for block in content_blocks
                if getattr(block, "type", "") == "text"
            ]
            usage = getattr(response, "usage", None)
            return CompletionResult(
                text="".join(text_parts),
                input_tokens=int(getattr(usage, "input_tokens", 0)) if usage else 0,
                output_tokens=int(getattr(usage, "output_tokens", 0)) if usage else 0,
                duration_ms=duration_ms,
            )
        raise BackendError(
            f"anthropic completion failed after {self._max_retries} attempts: {last_error!r}"
        )
