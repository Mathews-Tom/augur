"""IntelligenceBrief — the contract emitted by the gated LLM formatter.

The schema lives in the formatter package because it is the
formatter's output contract, even though the deterministic pathway
in this phase does not produce briefs. The secondary LLM formatter
in the next phase instantiates IntelligenceBrief values that pass
the forbidden-token linter and the ConsumerType enum gate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from augur_signals.models import ConsumerType


class IntelligenceBrief(BaseModel):
    """Gated LLM formatter output contract.

    ``actionable_for`` is constrained to the ConsumerType registry in
    docs/contracts/consumer-registry.md via the Pydantic field type;
    the closed-enum validator rechecks this at the formatter boundary
    so even dynamically-constructed instances fail loud on unknown
    values.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    brief_id: str
    signal_id: str
    headline: str
    body_markdown: str
    severity: Literal["high", "medium", "low"]
    actionable_for: list[ConsumerType] = Field(default_factory=list)
    interpretation_mode: Literal["llm_assisted"] = "llm_assisted"
    model: str
    prompt_hash: str
    forbidden_token_check: Literal["passed"] = "passed"  # noqa: S105
    schema_version: Literal["1.0.0"] = "1.0.0"
