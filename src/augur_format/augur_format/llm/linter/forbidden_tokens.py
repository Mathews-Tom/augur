"""Forbidden-token linter.

Rejects LLM output containing any phrase from the closed list in
config/forbidden_tokens.toml. The linter operates on the raw text
before the brief is constructed — a failing lint drops the brief
entirely per phase-4 §10.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ForbiddenTokenCheckResult(BaseModel):
    """Outcome of one forbidden-token check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    matched_phrases: list[str]


class ForbiddenTokenLinter:
    """Case-insensitive exact-phrase rejection."""

    def __init__(self, forbidden_phrases: Sequence[str]) -> None:
        self._phrases = [p.lower() for p in forbidden_phrases]

    @property
    def phrase_count(self) -> int:
        return len(self._phrases)

    def check_text(self, text: str) -> ForbiddenTokenCheckResult:
        lowered = text.lower()
        matched = [p for p in self._phrases if p in lowered]
        return ForbiddenTokenCheckResult(passed=not matched, matched_phrases=matched)

    def check_brief(self, brief: dict[str, object]) -> ForbiddenTokenCheckResult:
        headline = str(brief.get("headline", ""))
        body = str(brief.get("body_markdown", ""))
        return self.check_text(f"{headline}\n{body}")


def load_forbidden_phrases(path: Path) -> list[str]:
    """Flatten every [category].phrases table in the TOML into a single list.

    The file ships with categorized phrases (causal_narrative,
    price_projection, manipulation_speculation); the linter treats
    every category uniformly so phrase provenance is a config-layer
    concern.
    """
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    phrases: list[str] = []
    for section in raw.values():
        if isinstance(section, dict) and "phrases" in section:
            phrases.extend(str(p) for p in section["phrases"])
    return phrases
