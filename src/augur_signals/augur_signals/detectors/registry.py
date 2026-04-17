"""Registry and dispatch for signal detectors.

Per-market detectors receive a single (feature, snapshot, now) triple
and return an optional signal. The batch detector (cross-market
divergence) processes the full snapshot set for a polling cycle in one
call so the FDR controller sees all candidate p-values simultaneously.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from augur_signals.detectors.base import SignalDetector
from augur_signals.models import FeatureVector, MarketSignal, MarketSnapshot


class BatchDetector(Protocol):
    """Detectors that need the whole polling cycle at once."""

    detector_id: str

    def evaluate_batch(
        self,
        snapshots: dict[str, MarketSnapshot],
        now: datetime,
    ) -> list[MarketSignal]:
        """Process every market's latest snapshot as one batch."""
        ...


class DetectorRegistry:
    """Keeps track of registered detectors and dispatches observations to them."""

    def __init__(self) -> None:
        self._detectors: list[SignalDetector] = []
        self._batch: list[BatchDetector] = []

    def register(self, detector: SignalDetector) -> None:
        self._detectors.append(detector)

    def register_batch(self, detector: BatchDetector) -> None:
        self._batch.append(detector)

    def __len__(self) -> int:
        return len(self._detectors) + len(self._batch)

    def warmup_required(self) -> int:
        if not self._detectors:
            return 0
        return max(d.warmup_required() for d in self._detectors)

    def dispatch(
        self,
        market_id: str,
        feature: FeatureVector,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> list[MarketSignal]:
        """Run every per-market detector on one observation."""
        results: list[MarketSignal] = []
        for detector in self._detectors:
            signal = detector.ingest(market_id, feature, snapshot, now)
            if signal is not None:
                results.append(signal)
        return results

    def dispatch_batch(
        self,
        snapshots: dict[str, MarketSnapshot],
        now: datetime,
    ) -> list[MarketSignal]:
        """Run every batch detector on the current polling cycle."""
        results: list[MarketSignal] = []
        for detector in self._batch:
            results.extend(detector.evaluate_batch(snapshots, now))
        return results

    def detectors(self) -> Iterable[SignalDetector]:
        return tuple(self._detectors)
