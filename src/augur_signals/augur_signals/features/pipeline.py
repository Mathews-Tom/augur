"""Feature pipeline orchestrator.

Maintains per-market SnapshotBuffer plus a halt-aware EWMA baseline of
24h volume. For each ingested snapshot, computes momentum, volatility,
volume-ratio, bid/ask ratio, and spread over the canonical 5m / 15m /
1h / 4h wall-clock window labels. Windows are observation-count
internally; the mapping between wall-clock and observation count is
maintained per-market so tier changes do not corrupt feature
computation (see docs/architecture/adaptive-polling-spec.md
§Wall-Clock vs Observation-Count Window Reconciliation).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from augur_signals.features._config import FeaturePipelineConfig
from augur_signals.features.indicators import (
    bid_ask_ratio,
    price_momentum,
    spread_pct,
    volatility,
    volume_ratio,
)
from augur_signals.features.windows import SnapshotBuffer
from augur_signals.models import FeatureVector, MarketSnapshot

# Wall-clock window labels mapped to seconds.
_WINDOW_SECONDS: dict[str, int] = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14_400,
}


@dataclass(slots=True)
class _MarketFeatureState:
    """Per-market buffer, EWMA baseline, and polling-interval estimate."""

    buffer: SnapshotBuffer
    ewma_volume: float = 0.0
    ewma_initialized: bool = False
    polling_interval_seconds: int = 60
    last_timestamp_seconds: int | None = None
    observed_intervals: list[int] = field(default_factory=list)


class FeaturePipeline:
    """Computes per-market FeatureVectors from an incoming snapshot stream."""

    def __init__(self, config: FeaturePipelineConfig | None = None) -> None:
        self._config = config or FeaturePipelineConfig()
        self._markets: dict[str, _MarketFeatureState] = {}

    def ingest(self, snapshot: MarketSnapshot) -> FeatureVector | None:
        """Append *snapshot*, recompute the vector, and return it once warm."""
        state = self._markets.setdefault(
            snapshot.market_id,
            _MarketFeatureState(buffer=SnapshotBuffer(self._config.buffer_size)),
        )
        self._update_polling_interval(state, snapshot)
        state.buffer.append(snapshot)
        self._update_ewma(state, snapshot)
        if len(state.buffer) < self._config.warmup_size:
            return None
        return self._build_vector(snapshot, state)

    def _update_polling_interval(
        self, state: _MarketFeatureState, snapshot: MarketSnapshot
    ) -> None:
        ts_seconds = int(snapshot.timestamp.timestamp())
        if state.last_timestamp_seconds is not None:
            delta = ts_seconds - state.last_timestamp_seconds
            if 0 < delta <= self._config.max_polling_interval_seconds:
                state.observed_intervals.append(delta)
                if len(state.observed_intervals) > 20:
                    state.observed_intervals.pop(0)
                state.polling_interval_seconds = max(
                    1, sum(state.observed_intervals) // len(state.observed_intervals)
                )
        state.last_timestamp_seconds = ts_seconds

    def _update_ewma(self, state: _MarketFeatureState, snapshot: MarketSnapshot) -> None:
        alpha = self._config.ewma_alpha
        if not state.ewma_initialized:
            state.ewma_volume = snapshot.volume_24h
            state.ewma_initialized = True
            return
        # Halt-aware decay: polling gaps longer than 2x the expected
        # interval apply extra decay so the baseline does not freeze.
        gap_factor = 1
        if state.observed_intervals:
            expected = state.polling_interval_seconds
            actual = state.observed_intervals[-1]
            if actual > 2 * expected and expected > 0:
                gap_factor = max(1, actual // expected)
        decayed = (1 - alpha) ** gap_factor
        state.ewma_volume = decayed * state.ewma_volume + (1 - decayed) * snapshot.volume_24h

    def _build_vector(self, snapshot: MarketSnapshot, state: _MarketFeatureState) -> FeatureVector:
        def window_count(label: str) -> int:
            return max(2, _WINDOW_SECONDS[label] // state.polling_interval_seconds)

        w5m = state.buffer.window(window_count("5m"))
        w15m = state.buffer.window(window_count("15m"))
        w1h = state.buffer.window(window_count("1h"))
        w4h = state.buffer.window(window_count("4h"))

        return FeatureVector(
            market_id=snapshot.market_id,
            computed_at=snapshot.timestamp,
            price_momentum_5m=price_momentum(w5m),
            price_momentum_15m=price_momentum(w15m),
            price_momentum_1h=price_momentum(w1h),
            price_momentum_4h=price_momentum(w4h),
            volatility_5m=volatility(w5m),
            volatility_15m=volatility(w15m),
            volatility_1h=volatility(w1h),
            volatility_4h=volatility(w4h),
            volume_ratio_5m=volume_ratio(w5m, state.ewma_volume),
            volume_ratio_1h=volume_ratio(w1h, state.ewma_volume),
            bid_ask_ratio=bid_ask_ratio(snapshot),
            spread_pct=spread_pct(snapshot),
        )
