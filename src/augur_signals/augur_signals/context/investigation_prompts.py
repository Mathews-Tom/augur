"""Frozen investigation-prompt library keyed by (signal_type, market_category).

Loaded once at engine startup from data/investigation_prompts.toml. The
library raises on runtime additions; any change requires a config
reload. A coverage report enumerates the (signal_type, category)
tuples that have no registered prompts so the gaps surface at startup.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from augur_signals.models import SignalType


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Presence report for (signal_type, category) prompt entries."""

    total_categories: int
    covered: int
    missing: list[tuple[str, str]]


class PromptLibraryFrozenError(RuntimeError):
    """Raised when code attempts to mutate a frozen prompt library."""


class InvestigationPromptLibrary:
    """Read-only store of investigation prompts."""

    def __init__(
        self,
        entries: Iterable[tuple[SignalType, str, list[str]]],
    ) -> None:
        self._prompts: dict[tuple[str, str], tuple[str, ...]] = {}
        for signal_type, category, prompts in entries:
            key = (signal_type.value, category)
            if key in self._prompts:
                raise PromptLibraryFrozenError(f"duplicate prompt entry for {key}")
            self._prompts[key] = tuple(prompts)
        self._categories: set[str] = {key[1] for key in self._prompts}

    def lookup(self, signal_type: SignalType, category: str) -> list[str]:
        return list(self._prompts.get((signal_type.value, category), ()))

    def coverage_report(self, known_categories: Iterable[str]) -> CoverageReport:
        known = set(known_categories)
        missing: list[tuple[str, str]] = []
        for signal_type in SignalType:
            for category in known:
                if (signal_type.value, category) not in self._prompts:
                    missing.append((signal_type.value, category))
        total = len(SignalType) * len(known)
        return CoverageReport(
            total_categories=total,
            covered=total - len(missing),
            missing=missing,
        )

    @classmethod
    def from_toml(cls, path: Path) -> InvestigationPromptLibrary:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        entries_raw = raw.get("prompts", [])
        entries: list[tuple[SignalType, str, list[str]]] = []
        for item in entries_raw:
            entries.append(
                (
                    SignalType(item["signal_type"]),
                    str(item["market_category"]),
                    list(item.get("prompts", [])),
                )
            )
        return cls(entries)
