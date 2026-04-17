"""Closed-enum validators for the formatter boundary.

Briefs emitted by any formatter (deterministic today, LLM in the
gated secondary layer) carry an ``actionable_for`` list that must
contain only values from the ConsumerType registry in
docs/contracts/consumer-registry.md. Validation runs at the formatter
boundary; briefs with unknown values are dropped loudly, never
coerced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from augur_signals.models import ConsumerType


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of a closed-enum validation call."""

    valid: bool
    offending_values: list[str] = field(default_factory=list)


def validate_consumer_types(values: Sequence[str]) -> list[str]:
    """Return the subset of *values* that are not registered ConsumerType members.

    An empty list means every input is a valid consumer. The order of
    the offending values matches the caller's input order so error
    messages can point at the original list positions.
    """
    valid = {c.value for c in ConsumerType}
    return [v for v in values if v not in valid]


class ConsumerEnumValidator:
    """Validator callable used at the formatter boundary.

    The ``strict`` parameter is retained for the secondary LLM
    formatter, which may want to downgrade to a warning-and-drop
    during backfill; production deterministic output always runs in
    strict mode.
    """

    def __init__(self, *, strict: bool = True) -> None:
        self._strict = strict

    @property
    def strict(self) -> bool:
        return self._strict

    def validate_actionable_for(self, values: Sequence[str]) -> ValidationResult:
        """Check an ``actionable_for`` list against the ConsumerType registry."""
        offending = validate_consumer_types(values)
        return ValidationResult(valid=not offending, offending_values=offending)

    def validate_brief(self, brief: dict[str, object]) -> ValidationResult:
        """Validate a brief payload's actionable_for field.

        The input shape mirrors IntelligenceBrief's model_dump output;
        a missing actionable_for is treated as empty, not invalid. The
        method is primarily used by the LLM formatter gate once that
        layer lands; wiring it here keeps the closed-enum boundary in
        a single module.
        """
        actionable = brief.get("actionable_for", [])
        if not isinstance(actionable, list):
            return ValidationResult(valid=False, offending_values=["<not-a-list>"])
        string_values: list[str] = []
        bad: list[str] = []
        for value in actionable:
            if isinstance(value, str):
                string_values.append(value)
            else:
                bad.append(repr(value))
        offending = bad + validate_consumer_types(string_values)
        return ValidationResult(valid=not offending, offending_values=offending)
