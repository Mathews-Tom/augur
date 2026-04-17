"""LLMInterpreter — orchestrates the gated secondary formatter.

Composes the backend, prompt builder, forbidden-token linter, schema
validator, consumer gate, and provenance stamp into a single
``interpret`` call per SignalContext. Any failure (backend error,
forbidden token, invalid JSON, schema violation, storm suspension)
returns None; the deterministic pipeline proceeds unaffected.

Defense ordering:
1. Storm-mode short-circuit (before backend call).
2. Backend completion.
3. JSON parse — non-dict payloads drop the brief.
4. Forbidden-token lint against the parsed headline+body, not the raw
   JSON, so unicode-escape bypass cannot slip a forbidden phrase past
   the substring check.
5. Pydantic IntelligenceBrief construction (single validation pass).
6. Consumer gate trims actionable_for to consumers that opted in.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from augur_format.llm.backends.base import AbstractLLMBackend, BackendError
from augur_format.llm.linter.forbidden_tokens import ForbiddenTokenLinter
from augur_format.llm.models import SCHEMA_VERSION, IntelligenceBrief
from augur_format.llm.prompts.builder import PromptBuilder
from augur_format.llm.provenance.stamp import stamp
from augur_format.llm.routing.consumer_gate import ConsumerGate
from augur_signals.models import SignalContext


class LLMInterpreter:
    """Generate gated IntelligenceBriefs from SignalContext."""

    def __init__(
        self,
        backend: AbstractLLMBackend,
        prompt_builder: PromptBuilder,
        linter: ForbiddenTokenLinter,
        *,
        consumer_gate: ConsumerGate | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> None:
        self._backend = backend
        self._prompt_builder = prompt_builder
        self._linter = linter
        self._gate = consumer_gate
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._suspended = False

    @property
    def suspended(self) -> bool:
        return self._suspended

    def set_suspended(self, suspended: bool) -> None:
        """Toggle storm-mode suspension.

        When True, ``interpret`` returns None without calling the
        backend, matching phase-4 §11 coordination with the dedup
        layer's StormController.
        """
        self._suspended = suspended

    async def interpret(
        self, context: SignalContext, severity: str, *, now: datetime | None = None
    ) -> IntelligenceBrief | None:
        """Run the full gated-brief pipeline for *context*."""
        if self._suspended:
            return None
        system, user = self._prompt_builder.build(context)
        try:
            result = await self._backend.complete(system, user, self._max_tokens, self._temperature)
        except BackendError:
            return None
        try:
            parsed = json.loads(result.text)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        brief_payload: dict[str, object] = parsed
        # Lint the parsed headline+body — unicode escapes in the raw JSON
        # are normalized by the parser, closing the substring-bypass vector.
        headline = str(brief_payload.get("headline", ""))
        body = str(brief_payload.get("body_markdown", ""))
        lint = self._linter.check_text(f"{headline}\n{body}")
        if not lint.passed:
            return None
        generated_at = now if now is not None else datetime.now(tz=UTC)
        provenance = stamp(
            self._backend.backend_id,
            self._backend.model_id(),
            system,
            user,
        )
        brief_payload.update(
            {
                "brief_id": str(uuid4()),
                "signal_id": context.signal.signal_id,
                "severity": severity,
                "interpretation_mode": "llm_assisted",
                "model": provenance.model,
                "prompt_hash": provenance.prompt_hash,
                "formatter_version": provenance.formatter_version,
                "generated_at": generated_at,
                "forbidden_token_check": "passed",
                "schema_version": SCHEMA_VERSION,
            }
        )
        try:
            brief = IntelligenceBrief.model_validate(brief_payload)
        except ValidationError:
            return None
        if self._gate is not None:
            allowed = self._gate.filter_consumers(brief.actionable_for, brief)
            if not allowed:
                return None
            if allowed != list(brief.actionable_for):
                brief = brief.model_copy(update={"actionable_for": allowed})
        return brief
