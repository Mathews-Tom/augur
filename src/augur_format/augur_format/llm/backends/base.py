"""AbstractLLMBackend protocol and completion result model.

Concrete adapters (Ollama, Anthropic) implement the same async
``complete`` surface so the interpreter dispatches uniformly. The
completion result exposes only the fields downstream actually needs:
the raw text, token counts for observability, and the duration in
milliseconds for the generation-latency SLO.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class CompletionResult(BaseModel):
    """One backend completion's payload plus timing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0


class BackendError(RuntimeError):
    """Raised when a backend cannot produce a completion."""


class AbstractLLMBackend(Protocol):
    """Uniform surface every LLM backend adapter implements."""

    backend_id: str

    async def complete(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        """Return the model's completion for (*system*, *prompt*)."""
        ...

    def model_id(self) -> str:
        """Return the active model identifier (e.g. ``gemma2:27b``)."""
        ...

    async def health_check(self) -> bool:
        """Verify the backend is reachable and serving the configured model."""
        ...
