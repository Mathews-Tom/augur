"""Adaptive polling scheduler with hysteresis and rate-limit budgeting.

Implements the state machine in docs/architecture/adaptive-polling-spec.md:
per-market tier assignment (hot / warm / cool / cold), asymmetric
promotion/demotion thresholds on volume_ratio_1h, and hysteresis bands
that prevent flapping. Rate-limit pressure is observed by the caller
and fed back in via :meth:`observe_platform_pressure`; when a platform
exceeds 80 % of its budget, the scheduler demotes its lowest-priority
hot markets to warm until pressure drops below 70 %.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from augur_signals.ingestion._config import PollingBody

Tier = Literal["hot", "warm", "cool", "cold"]


@dataclass(slots=True)
class _MarketState:
    """Per-market polling state carried by the scheduler."""

    tier: Tier
    closes_in_seconds: int = 0
    volume_ratio_1h: float = 1.0
    seconds_since_last_signal: int | None = None


@dataclass(frozen=True, slots=True)
class RateLimitPressureEvent:
    """Emitted when a platform's request rate exceeds 80 % of its cap."""

    platform: str
    utilization: float


class AdaptivePollingScheduler:
    """Per-market polling-tier state machine."""

    def __init__(self, config: PollingBody) -> None:
        self._config = config
        self._states: dict[str, _MarketState] = {}
        self._pressure_events: list[RateLimitPressureEvent] = []

    def register(self, market_id: str, initial_tier: Tier = "cool") -> None:
        """Add *market_id* to the scheduled set at *initial_tier*."""
        self._states[market_id] = _MarketState(tier=initial_tier)

    def current_tier(self, market_id: str) -> Tier:
        return self._states[market_id].tier

    def interval_seconds(self, market_id: str) -> int:
        tier = self._states[market_id].tier
        if tier == "hot":
            return self._config.hot_interval_s
        if tier == "warm":
            return self._config.warm_interval_s
        if tier == "cool":
            return self._config.cool_interval_s
        return self._config.cold_interval_s

    def update_market_state(
        self,
        market_id: str,
        *,
        volume_ratio_1h: float,
        has_active_signal: bool,
        closes_in_seconds: int,
    ) -> None:
        """Apply a single tick's observation and re-evaluate the tier."""
        state = self._states[market_id]
        state.volume_ratio_1h = volume_ratio_1h
        state.closes_in_seconds = closes_in_seconds
        state.seconds_since_last_signal = 0 if has_active_signal else None
        state.tier = self._next_tier(state)

    def observe_platform_pressure(self, platform: str, utilization: float) -> None:
        """Record per-platform utilization; demote hot markets when high."""
        if utilization > 0.80:
            self._pressure_events.append(
                RateLimitPressureEvent(platform=platform, utilization=utilization)
            )
            if utilization > 0.80:
                self._demote_lowest_priority_hot(1)

    def drain_pressure_events(self) -> list[RateLimitPressureEvent]:
        """Return and clear the pending rate-limit pressure events."""
        events, self._pressure_events = self._pressure_events, []
        return events

    def _demote_lowest_priority_hot(self, count: int) -> None:
        hot = [(mid, state) for mid, state in self._states.items() if state.tier == "hot"]
        # Sort by lowest volume_ratio_1h so the least active hot market demotes first.
        hot.sort(key=lambda pair: pair[1].volume_ratio_1h)
        for mid, _state in hot[:count]:
            self._states[mid].tier = "warm"

    def _next_tier(self, state: _MarketState) -> Tier:
        bands = self._config.hysteresis
        ratio = state.volume_ratio_1h
        closes_within_24h = 0 < state.closes_in_seconds < 86_400
        has_signal = state.seconds_since_last_signal is not None

        if state.tier == "cold" and ratio > bands.cool_promote:
            return "cool"
        if state.tier == "cool":
            if ratio > bands.warm_promote or closes_within_24h:
                return "warm"
            if ratio < bands.cool_demote:
                return "cold"
        if state.tier == "warm":
            if ratio > bands.hot_promote or has_signal:
                return "hot"
            if ratio < bands.warm_demote and not closes_within_24h:
                return "cool"
        if state.tier == "hot" and ratio < bands.hot_demote and not has_signal:
            return "warm"
        return state.tier

    # Exposed for tests and ops tooling that need to reset state.
    def _reset_market(self, market_id: str, tier: Tier) -> None:
        self._states[market_id] = _MarketState(tier=tier)


__all__ = [
    "AdaptivePollingScheduler",
    "RateLimitPressureEvent",
    "Tier",
]
