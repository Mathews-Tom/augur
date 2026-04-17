"""IntelligenceBrief schema validator wrapping the Pydantic model.

Validates a brief payload by attempting IntelligenceBrief construction.
Pydantic's ValidationError surfaces the specific field violation; the
validator translates that into a stable ValidationResult shape the
interpreter consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from augur_format.llm.models import IntelligenceBrief


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of one brief-schema validation."""

    ok: bool
    errors: list[str] = field(default_factory=list)


class SchemaValidator:
    """Validate a raw brief dict against the IntelligenceBrief contract."""

    def validate(self, brief_dict: dict[str, object]) -> ValidationResult:
        try:
            IntelligenceBrief.model_validate(brief_dict)
        except ValidationError as err:
            errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors()]
            return ValidationResult(ok=False, errors=errors)
        return ValidationResult(ok=True)
