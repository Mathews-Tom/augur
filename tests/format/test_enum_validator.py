"""Tests for the closed-enum validator and schema loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from augur_format.validate.enum_check import (
    ConsumerEnumValidator,
    validate_consumer_types,
)
from augur_format.validate.schema_check import SchemaNotFoundError, load_schema


@pytest.mark.unit
def test_validate_returns_empty_on_all_valid() -> None:
    assert validate_consumer_types(["macro_research_agent", "dashboard"]) == []


@pytest.mark.unit
def test_validate_returns_offending_values() -> None:
    offending = validate_consumer_types(["macro_research_agent", "nyt_newsroom"])
    assert offending == ["nyt_newsroom"]


@pytest.mark.unit
def test_validator_rejects_brief_with_unknown_consumer() -> None:
    validator = ConsumerEnumValidator()
    result = validator.validate_brief({"actionable_for": ["macro_research_agent", "nyt_newsroom"]})
    assert not result.valid
    assert "nyt_newsroom" in result.offending_values


@pytest.mark.unit
def test_validator_accepts_all_known_consumers() -> None:
    validator = ConsumerEnumValidator()
    result = validator.validate_brief(
        {
            "actionable_for": [
                "macro_research_agent",
                "geopolitical_research_agent",
                "dashboard",
            ]
        }
    )
    assert result.valid
    assert result.offending_values == []


@pytest.mark.unit
def test_validator_rejects_non_string_members() -> None:
    validator = ConsumerEnumValidator()
    result = validator.validate_brief({"actionable_for": ["dashboard", 42]})
    assert not result.valid


@pytest.mark.unit
def test_validator_rejects_actionable_for_not_a_list() -> None:
    validator = ConsumerEnumValidator()
    result = validator.validate_brief({"actionable_for": "dashboard"})
    assert not result.valid


@pytest.mark.unit
def test_validator_missing_field_treated_as_empty_list() -> None:
    validator = ConsumerEnumValidator()
    result = validator.validate_brief({})
    assert result.valid


@pytest.mark.unit
def test_load_schema_raises_on_missing(tmp_path: Path) -> None:
    with pytest.raises(SchemaNotFoundError):
        load_schema("DoesNotExist", "1.0.0", root=tmp_path)


@pytest.mark.unit
def test_load_schema_reads_known_schema() -> None:
    schema = load_schema("MarketSignal", "1.0.0")
    assert schema["title"] == "MarketSignal"
