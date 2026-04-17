"""Pydantic data contracts for Augur signal extraction.

Schemas are authoritative in docs/contracts/schema-and-versioning.md.
Every exported model sets schema_version to "1.0.0"; major-version
bumps follow the versioning policy in that document.
"""

from __future__ import annotations

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

__all__ = [
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
