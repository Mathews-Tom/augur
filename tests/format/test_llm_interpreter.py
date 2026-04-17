"""End-to-end tests for the LLMInterpreter orchestrator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from augur_format.llm.backends.base import (
    AbstractLLMBackend,
    BackendError,
    CompletionResult,
)
from augur_format.llm.interpreter import LLMInterpreter
from augur_format.llm.linter.forbidden_tokens import ForbiddenTokenLinter
from augur_format.llm.linter.schema_check import SchemaValidator
from augur_format.llm.prompts.builder import PromptBuilder
from augur_signals.models import (
    InterpretationMode,
    MarketSignal,
    SignalContext,
    SignalType,
    new_signal_id,
)

FORBIDDEN = ["may be driven by", "likely reflects"]


def _context() -> SignalContext:
    signal = MarketSignal(
        signal_id=new_signal_id(),
        market_id="kalshi_fed",
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.8,
        direction=1,
        confidence=0.72,
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


@dataclass
class _StubBackend(AbstractLLMBackend):
    backend_id: str = "stub"
    _model: str = "stub-model"
    _responses: list[str] | None = None
    _exception: BaseException | None = None

    def model_id(self) -> str:
        return self._model

    async def health_check(self) -> bool:
        return True

    async def complete(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        del system, prompt, max_tokens, temperature
        if self._exception is not None:
            raise self._exception
        if not self._responses:
            raise RuntimeError("no canned response")
        text = self._responses.pop(0)
        return CompletionResult(text=text, input_tokens=10, output_tokens=20, duration_ms=5)


_VALID_RESPONSE = json.dumps(
    {
        "headline": "Fed holds rates",
        "body_markdown": "The Fed left the target range unchanged.",
        "actionable_for": ["dashboard"],
    }
)


def _interpreter(
    backend: _StubBackend,
    forbidden: list[str] | None = None,
) -> LLMInterpreter:
    return LLMInterpreter(
        backend,
        PromptBuilder(forbidden or FORBIDDEN),
        ForbiddenTokenLinter(forbidden or FORBIDDEN),
        SchemaValidator(),
    )


@pytest.mark.asyncio
async def test_happy_path_emits_brief() -> None:
    backend = _StubBackend(_responses=[_VALID_RESPONSE])
    interpreter = _interpreter(backend)
    brief = await interpreter.interpret(
        _context(),
        severity="high",
        now=datetime(2026, 3, 15, 12, 5, tzinfo=UTC),
    )
    assert brief is not None
    assert brief.headline == "Fed holds rates"
    assert brief.severity == "high"
    assert brief.interpretation_mode == "llm_assisted"
    assert brief.prompt_hash != ""
    assert brief.forbidden_token_check == "passed"  # noqa: S105


@pytest.mark.asyncio
async def test_forbidden_token_drops_brief() -> None:
    tainted = json.dumps(
        {
            "headline": "Hold",
            "body_markdown": "Prices may be driven by external news.",
            "actionable_for": ["dashboard"],
        }
    )
    backend = _StubBackend(_responses=[tainted])
    interpreter = _interpreter(backend)
    brief = await interpreter.interpret(_context(), severity="medium")
    assert brief is None


@pytest.mark.asyncio
async def test_invalid_json_drops_brief() -> None:
    backend = _StubBackend(_responses=["{this is not json"])
    interpreter = _interpreter(backend)
    brief = await interpreter.interpret(_context(), severity="medium")
    assert brief is None


@pytest.mark.asyncio
async def test_unknown_consumer_drops_brief() -> None:
    bad_consumer = json.dumps(
        {
            "headline": "Hold",
            "body_markdown": "Update.",
            "actionable_for": ["not_a_consumer"],
        }
    )
    backend = _StubBackend(_responses=[bad_consumer])
    interpreter = _interpreter(backend)
    brief = await interpreter.interpret(_context(), severity="medium")
    assert brief is None


@pytest.mark.asyncio
async def test_backend_error_drops_brief() -> None:
    backend = _StubBackend(_exception=BackendError("down"))
    interpreter = _interpreter(backend)
    brief = await interpreter.interpret(_context(), severity="medium")
    assert brief is None


@pytest.mark.asyncio
async def test_storm_suspension_short_circuits_before_backend_call() -> None:
    backend = _StubBackend(_responses=[_VALID_RESPONSE])
    interpreter = _interpreter(backend)
    interpreter.set_suspended(True)
    brief = await interpreter.interpret(_context(), severity="high")
    assert brief is None
    # Backend call was not made; the canned response is still pending.
    assert backend._responses == [_VALID_RESPONSE]


@pytest.mark.asyncio
async def test_resuming_from_suspension_allows_next_brief() -> None:
    backend = _StubBackend(_responses=[_VALID_RESPONSE])
    interpreter = _interpreter(backend)
    interpreter.set_suspended(True)
    suspended = await interpreter.interpret(_context(), severity="high")
    assert suspended is None
    interpreter.set_suspended(False)
    brief = await interpreter.interpret(
        _context(),
        severity="high",
        now=datetime(2026, 3, 15, 12, 5, tzinfo=UTC),
    )
    assert brief is not None


@pytest.mark.asyncio
async def test_overlong_headline_drops_brief() -> None:
    long_headline = json.dumps(
        {
            "headline": "x" * 100,
            "body_markdown": "ok",
            "actionable_for": ["dashboard"],
        }
    )
    backend = _StubBackend(_responses=[long_headline])
    interpreter = _interpreter(backend)
    brief = await interpreter.interpret(_context(), severity="low")
    assert brief is None
