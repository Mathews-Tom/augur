"""Tests for the IntelligenceBrief contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from augur_format.llm.models import IntelligenceBrief


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "brief_id": "brief-1",
        "signal_id": "signal-1",
        "headline": "Fed holds rates per announcement",
        "body_markdown": "## Summary\n- Fed held at the current range.",
        "severity": "high",
        "actionable_for": ["macro_research_agent", "dashboard"],
        "model": "gemma2:27b@ollama",
        "prompt_hash": "a" * 64,
        "formatter_version": "0.0.0",
        "generated_at": datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_canonical_payload_validates() -> None:
    brief = IntelligenceBrief.model_validate(_payload())
    assert brief.interpretation_mode == "llm_assisted"
    assert brief.forbidden_token_check == "passed"  # noqa: S105
    assert brief.schema_version == "1.0.0"


@pytest.mark.unit
def test_headline_over_90_chars_rejected() -> None:
    with pytest.raises(ValidationError, match="at most 90 characters"):
        IntelligenceBrief.model_validate(_payload(headline="x" * 91))


@pytest.mark.unit
def test_body_over_800_chars_rejected() -> None:
    with pytest.raises(ValidationError, match="at most 800 characters"):
        IntelligenceBrief.model_validate(_payload(body_markdown="x" * 801))


@pytest.mark.unit
def test_unknown_consumer_type_rejected() -> None:
    with pytest.raises(ValidationError):
        IntelligenceBrief.model_validate(_payload(actionable_for=["not_a_consumer"]))


@pytest.mark.unit
def test_interpretation_mode_cannot_be_overridden() -> None:
    with pytest.raises(ValidationError):
        IntelligenceBrief.model_validate(_payload(interpretation_mode="deterministic"))


@pytest.mark.unit
def test_forbidden_token_check_cannot_be_overridden() -> None:
    with pytest.raises(ValidationError):
        IntelligenceBrief.model_validate(_payload(forbidden_token_check="failed"))  # noqa: S106


@pytest.mark.unit
def test_model_is_frozen() -> None:
    brief = IntelligenceBrief.model_validate(_payload())
    with pytest.raises(ValidationError):
        brief.headline = "mutated"  # type: ignore[misc]


@pytest.mark.unit
def test_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        IntelligenceBrief.model_validate({**_payload(), "unexpected": 1})
