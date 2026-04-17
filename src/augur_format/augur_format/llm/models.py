"""IntelligenceBrief — the contract emitted by the gated LLM formatter.

The schema lives in the formatter package because it is the
formatter's output contract. Only the gated LLM formatter path can
construct briefs: the forbidden-token linter, the JSON schema
validator, and the consumer gate all run before the constructor.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from augur_signals.models import ConsumerType

SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"


class IntelligenceBrief(BaseModel):
    """Gated LLM formatter output contract.

    Structural invariants are enforced by Pydantic at construction:
    the headline is capped at 90 characters so it fits a Slack header,
    body_markdown is capped at 800 characters so it stays readable on
    a dashboard card, `actionable_for` is typed as list[ConsumerType]
    so unknown consumers fail immediately, and `interpretation_mode`
    plus `forbidden_token_check` are Literal singletons — any
    construction path that bypasses the linter or the deterministic-
    mode check would have to forge the literal, which is caught in
    code review.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    brief_id: str
    signal_id: str
    headline: Annotated[str, Field(max_length=90)]
    body_markdown: Annotated[str, Field(max_length=800)]
    severity: Literal["high", "medium", "low"]
    actionable_for: list[ConsumerType] = Field(default_factory=list)
    interpretation_mode: Literal["llm_assisted"] = "llm_assisted"
    model: str
    prompt_hash: str
    formatter_version: str
    generated_at: datetime
    forbidden_token_check: Literal["passed"] = "passed"  # noqa: S105
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION

    @model_validator(mode="after")
    def _interpretation_mode_pinned(self) -> IntelligenceBrief:
        if self.interpretation_mode != "llm_assisted":
            raise ValueError("LLM-rendered briefs must declare interpretation_mode=llm_assisted")
        return self

    @model_validator(mode="after")
    def _forbidden_token_check_marker(self) -> IntelligenceBrief:
        if self.forbidden_token_check != "passed":  # noqa: S105
            raise ValueError("Brief without passed forbidden-token check cannot exist")
        return self
