"""Manipulation detector — aggregates signature checks per signal.

The detector is called once per candidate signal, after the detector
layer fires but before dedup. It runs every signature in
docs/methodology/manipulation-taxonomy.md and returns the matched
flags. The list is always present and always a list — never None.

The detector is descriptive, not prescriptive: it does not suppress
signals. Consumers apply their own policy per the taxonomy doc.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from augur_signals.ingestion.base import RawTrade
from augur_signals.manipulation._config import ManipulationConfig
from augur_signals.manipulation.signatures import (
    BookEvent,
    cancel_replace_burst,
    pre_resolution_window,
    single_counterparty_concentration,
    size_vs_depth_outlier,
    thin_book_during_move,
)
from augur_signals.models import ManipulationFlag, MarketSignal, MarketSnapshot


class ManipulationDetector:
    """Evaluates every signature against a candidate signal."""

    def __init__(self, config: ManipulationConfig) -> None:
        self._config = config

    def evaluate(
        self,
        signal: MarketSignal,
        recent_trades: Sequence[RawTrade],
        recent_book_events: Sequence[BookEvent],
        recent_snapshots: Sequence[MarketSnapshot],
        market_closes_at: datetime | None,
    ) -> list[ManipulationFlag]:
        flags: list[ManipulationFlag] = []
        herfindahl = single_counterparty_concentration(recent_trades)
        if herfindahl > self._config.herfindahl_threshold:
            flags.append(ManipulationFlag.SINGLE_COUNTERPARTY_CONCENTRATION)
        if recent_trades and recent_snapshots:
            # Check every large trade against the snapshot depth prior to it.
            total_depth = recent_snapshots[-1].liquidity if recent_snapshots else 0.0
            for trade in recent_trades:
                if size_vs_depth_outlier(trade, total_depth, self._config.size_vs_depth_threshold):
                    flags.append(ManipulationFlag.SIZE_VS_DEPTH_OUTLIER)
                    break
        if cancel_replace_burst(
            recent_book_events,
            self._config.cancel_replace_window_seconds,
            self._config.cancel_replace_min_count,
        ):
            flags.append(ManipulationFlag.CANCEL_REPLACE_BURST)
        if thin_book_during_move(recent_snapshots, self._config.thin_book_min_depth):
            flags.append(ManipulationFlag.THIN_BOOK_DURING_MOVE)
        if pre_resolution_window(
            signal.detected_at,
            market_closes_at,
            self._config.pre_resolution_window_seconds,
        ):
            flags.append(ManipulationFlag.PRE_RESOLUTION_WINDOW)
        return flags


def attach_flags(signal: MarketSignal, flags: list[ManipulationFlag]) -> MarketSignal:
    """Return a new MarketSignal with *flags* attached.

    MarketSignal is frozen; the update must go through `model_copy`
    so Pydantic re-runs the calibration_provenance validator on the
    result.
    """
    return signal.model_copy(update={"manipulation_flags": flags})
