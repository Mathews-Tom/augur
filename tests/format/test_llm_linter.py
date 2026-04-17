"""Tests for forbidden-token linter, schema validator, stamp, gate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from augur_format.llm.linter.forbidden_tokens import (
    ForbiddenTokenLinter,
    load_forbidden_phrases,
)
from augur_format.llm.linter.schema_check import SchemaValidator
from augur_format.llm.models import IntelligenceBrief
from augur_format.llm.provenance.stamp import stamp
from augur_format.llm.routing.consumer_gate import ConsumerGate
from augur_signals.models import ConsumerType


@pytest.mark.unit
def test_linter_rejects_each_configured_phrase() -> None:
    phrases = load_forbidden_phrases(Path("config/forbidden_tokens.toml"))
    assert phrases  # sanity: at least one phrase loaded from the shipped file
    linter = ForbiddenTokenLinter(phrases)
    for phrase in phrases:
        result = linter.check_text(f"The market {phrase} a rate change.")
        assert not result.passed
        assert phrase.lower() in result.matched_phrases


@pytest.mark.unit
def test_linter_is_case_insensitive() -> None:
    linter = ForbiddenTokenLinter(["may be driven by"])
    assert not linter.check_text("Prices May Be Driven By macro moves").passed


@pytest.mark.unit
def test_linter_accepts_clean_text() -> None:
    linter = ForbiddenTokenLinter(["may be driven by"])
    result = linter.check_text("The Fed left the rate range unchanged.")
    assert result.passed
    assert result.matched_phrases == []


@pytest.mark.unit
def test_linter_check_brief_combines_headline_and_body() -> None:
    linter = ForbiddenTokenLinter(["suggests that"])
    result = linter.check_brief(
        {"headline": "Update", "body_markdown": "The move suggests that a cut is due."}
    )
    assert not result.passed


@pytest.mark.unit
def test_schema_validator_accepts_valid_payload() -> None:
    validator = SchemaValidator()
    result = validator.validate(
        {
            "brief_id": "b1",
            "signal_id": "s1",
            "headline": "h",
            "body_markdown": "body",
            "severity": "high",
            "actionable_for": ["dashboard"],
            "model": "gemma2:27b@ollama",
            "prompt_hash": "a" * 64,
            "formatter_version": "0.0.0",
            "generated_at": "2026-03-15T12:00:00Z",
        }
    )
    assert result.ok


@pytest.mark.unit
def test_schema_validator_rejects_over_length_headline() -> None:
    validator = SchemaValidator()
    result = validator.validate(
        {
            "brief_id": "b1",
            "signal_id": "s1",
            "headline": "x" * 91,
            "body_markdown": "body",
            "severity": "high",
            "actionable_for": ["dashboard"],
            "model": "m@b",
            "prompt_hash": "a" * 64,
            "formatter_version": "0.0.0",
            "generated_at": "2026-03-15T12:00:00Z",
        }
    )
    assert not result.ok
    assert any("headline" in e for e in result.errors)


@pytest.mark.unit
def test_schema_validator_rejects_unknown_consumer() -> None:
    validator = SchemaValidator()
    result = validator.validate(
        {
            "brief_id": "b1",
            "signal_id": "s1",
            "headline": "h",
            "body_markdown": "body",
            "severity": "high",
            "actionable_for": ["not_a_consumer"],
            "model": "m@b",
            "prompt_hash": "a" * 64,
            "formatter_version": "0.0.0",
            "generated_at": "2026-03-15T12:00:00Z",
        }
    )
    assert not result.ok


@pytest.mark.unit
def test_stamp_is_reproducible() -> None:
    s1 = stamp("ollama", "gemma2:27b", "system", "user")
    s2 = stamp("ollama", "gemma2:27b", "system", "user")
    assert s1.prompt_hash == s2.prompt_hash
    assert s1.model == "gemma2:27b@ollama"
    assert len(s1.prompt_hash) == 64


@pytest.mark.unit
def test_stamp_hash_changes_on_prompt_change() -> None:
    a = stamp("ollama", "gemma2:27b", "system", "user-a")
    b = stamp("ollama", "gemma2:27b", "system", "user-b")
    assert a.prompt_hash != b.prompt_hash


@pytest.mark.unit
def test_consumer_gate_allows_opted_in() -> None:
    gate = ConsumerGate([ConsumerType.DASHBOARD])
    brief = IntelligenceBrief.model_validate(
        {
            "brief_id": "b1",
            "signal_id": "s1",
            "headline": "h",
            "body_markdown": "body",
            "severity": "high",
            "actionable_for": ["dashboard"],
            "model": "m@b",
            "prompt_hash": "a" * 64,
            "formatter_version": "0.0.0",
            "generated_at": datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        }
    )
    assert gate.is_eligible(ConsumerType.DASHBOARD, brief)
    assert not gate.is_eligible(ConsumerType.MACRO_RESEARCH_AGENT, brief)


@pytest.mark.unit
def test_consumer_gate_filters_list() -> None:
    gate = ConsumerGate([ConsumerType.DASHBOARD])
    brief = IntelligenceBrief.model_validate(
        {
            "brief_id": "b1",
            "signal_id": "s1",
            "headline": "h",
            "body_markdown": "body",
            "severity": "high",
            "actionable_for": ["dashboard"],
            "model": "m@b",
            "prompt_hash": "a" * 64,
            "formatter_version": "0.0.0",
            "generated_at": datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        }
    )
    kept = gate.filter_consumers([ConsumerType.MACRO_RESEARCH_AGENT, ConsumerType.DASHBOARD], brief)
    assert kept == [ConsumerType.DASHBOARD]
