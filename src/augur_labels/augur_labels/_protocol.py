"""Labeling-protocol constants shared across modules.

The protocol version is the single source of truth for
``label_protocol_version`` on every produced NewsworthyEvent and
SignalLabel. Bumping this constant triggers recomputation of any
calibration metric derived from the affected labels per
docs/methodology/labeling-protocol.md §Versioning.
"""

from __future__ import annotations

LABEL_PROTOCOL_VERSION: str = "1.0"

MIN_DISTINCT_QUALIFYING_SOURCES: int = 2
