"""Pydantic data contracts for Augur signal extraction.

Schemas are authoritative in docs/contracts/schema-and-versioning.md.
Every exported model sets schema_version to "1.0.0"; major-version
bumps follow the versioning policy in that document.

MODELS_SCHEMA_VERSION is the single source of truth for the major
schema contract. Dependent packages (augur-labels, augur-format)
assert compatibility against it at import time — see
docs/contracts/cross-package-compatibility.md.
"""

from __future__ import annotations

from typing import Final

from augur_signals.models._identifiers import new_signal_id
from augur_signals.models.context import RelatedMarketState, SignalContext
from augur_signals.models.enums import (
    ConsumerType,
    InterpretationMode,
    ManipulationFlag,
    SignalType,
)
from augur_signals.models.features import FeatureVector
from augur_signals.models.signal import MarketSignal
from augur_signals.models.snapshot import MarketSnapshot

MODELS_SCHEMA_VERSION: Final[str] = "1.0.0"

__all__ = [
    "MODELS_SCHEMA_VERSION",
    "ConsumerType",
    "FeatureVector",
    "InterpretationMode",
    "ManipulationFlag",
    "MarketSignal",
    "MarketSnapshot",
    "RelatedMarketState",
    "SignalContext",
    "SignalType",
    "new_signal_id",
]
