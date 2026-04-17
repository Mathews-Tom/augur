"""Book-imbalance detector — depth-gated bid/ask ratio with persistence.

Signals fire only when (1) the market has sufficient total resting
depth (the depth gate keeps the detector silent on thin books where
the imbalance is likely a manipulation artifact), and (2) the
imbalance persists for `persistence_snapshots` consecutive ticks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from augur_signals.calibration.liquidity_tier import banding
from augur_signals.detectors._config import BookImbalanceConfig
from augur_signals.models import (
    FeatureVector,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)


class BookImbalanceDetector:
    """Detector for sustained bid/ask depth imbalance."""

    detector_id: str = "book_imbalance_depth_persist_v1"
    signal_type: SignalType = SignalType.BOOK_IMBALANCE

    def __init__(
        self,
        config: BookImbalanceConfig,
        calibration_provenance: str = "book_imbalance_depth_persist_v1@identity_v0",
    ) -> None:
        self._config = config
        self._provenance = calibration_provenance
        self._consecutive_bull: dict[str, int] = {}
        self._consecutive_bear: dict[str, int] = {}

    def warmup_required(self) -> int:
        return self._config.persistence_snapshots

    def ingest(
        self,
        market_id: str,
        feature: FeatureVector,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> MarketSignal | None:
        if snapshot.closes_at is not None:
            remaining = (snapshot.closes_at - now).total_seconds()
            if 0.0 <= remaining < self._config.resolution_exclusion_seconds:
                return None
        if snapshot.liquidity < self._config.minimum_total_depth:
            self._consecutive_bull[market_id] = 0
            self._consecutive_bear[market_id] = 0
            return None
        ratio = feature.bid_ask_ratio
        if ratio is None:
            return None
        bull = self._consecutive_bull.get(market_id, 0)
        bear = self._consecutive_bear.get(market_id, 0)
        if ratio >= self._config.bullish_threshold:
            bull += 1
            bear = 0
        elif ratio <= self._config.bearish_threshold:
            bear += 1
            bull = 0
        else:
            bull = 0
            bear = 0
        self._consecutive_bull[market_id] = bull
        self._consecutive_bear[market_id] = bear
        persistence = self._config.persistence_snapshots
        if bull < persistence and bear < persistence:
            return None
        direction: Literal[-1, 0, 1] = 1 if bull >= persistence else -1
        magnitude = abs(ratio - 0.5) * 2.0
        tier = banding(snapshot.volume_24h)
        # Reset after firing so the next sustained imbalance requires a
        # fresh persistence window.
        self._consecutive_bull[market_id] = 0
        self._consecutive_bear[market_id] = 0
        return MarketSignal(
            signal_id=new_signal_id(),
            market_id=market_id,
            platform=snapshot.platform,
            signal_type=self.signal_type,
            magnitude=min(1.0, magnitude),
            direction=direction,
            confidence=min(1.0, magnitude),
            fdr_adjusted=False,
            detected_at=now,
            window_seconds=persistence * 60,
            liquidity_tier=tier,
            raw_features={
                "bid_ask_ratio": ratio,
                "liquidity": snapshot.liquidity,
                "calibration_provenance": self._provenance,
            },
        )

    def state_dict(self, market_id: str) -> dict[str, Any]:
        return {
            "consecutive_bull": self._consecutive_bull.get(market_id, 0),
            "consecutive_bear": self._consecutive_bear.get(market_id, 0),
        }

    def load_state(self, market_id: str, state: dict[str, Any]) -> None:
        self._consecutive_bull[market_id] = int(state.get("consecutive_bull", 0))
        self._consecutive_bear[market_id] = int(state.get("consecutive_bear", 0))

    def reset(self, market_id: str) -> None:
        self._consecutive_bull.pop(market_id, None)
        self._consecutive_bear.pop(market_id, None)
