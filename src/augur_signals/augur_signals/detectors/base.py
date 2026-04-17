"""SignalDetector protocol.

Every detector implements this surface. `now` is a parameter rather
than sourced from `datetime.now()` so backtests reproduce live
behavior bit-for-bit; the CI AST lint in scripts/ rejects any detector
module that calls `datetime.now()` directly.

Each detector is stateful per market (`state_dict` / `load_state`
so detector progress survives process restarts) and serializable for
the engine's periodic checkpoint. Detectors return `None` when no
signal fires; a `MarketSignal` instance carries the full calibrated
event per docs/contracts/schema-and-versioning.md §MarketSignal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from augur_signals.models import FeatureVector, MarketSignal, MarketSnapshot, SignalType


class SignalDetector(Protocol):
    """Common surface for per-market detectors."""

    detector_id: str
    signal_type: SignalType

    def warmup_required(self) -> int:
        """Number of observations required before the detector can fire."""
        ...

    def ingest(
        self,
        market_id: str,
        feature: FeatureVector,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> MarketSignal | None:
        """Process one observation; return a signal or None."""
        ...

    def state_dict(self, market_id: str) -> dict[str, Any]:
        """Serialize per-market state for checkpointing."""
        ...

    def load_state(self, market_id: str, state: dict[str, Any]) -> None:
        """Restore per-market state from a prior checkpoint."""
        ...

    def reset(self, market_id: str) -> None:
        """Clear all state for *market_id*."""
        ...
