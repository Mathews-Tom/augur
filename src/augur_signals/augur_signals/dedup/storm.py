"""Storm detection state machine.

Tracks raw signal arrival rate and bus queue depth against the
trigger / recovery thresholds in
docs/architecture/deduplication-and-storms.md §Storm Detection. Enters
storm mode on either trigger, exits only when both recovery
conditions hold simultaneously.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from augur_signals.dedup._config import StormSettings


@dataclass(frozen=True, slots=True)
class StormState:
    in_storm: bool
    started_at: datetime | None
    ended_at: datetime | None


@dataclass(slots=True)
class _RateTracker:
    """Rolling rate-of-arrival estimator over a bounded time window."""

    window_seconds: int
    events: deque[datetime] = field(default_factory=deque)

    def observe(self, now: datetime, count: int) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        for _ in range(count):
            self.events.append(now)
        while self.events and self.events[0] < cutoff:
            self.events.popleft()

    def rate_per_second(self) -> float:
        if not self.events:
            return 0.0
        return len(self.events) / max(1.0, float(self.window_seconds))


class StormController:
    """Entry / exit logic for storm mode."""

    def __init__(self, config: StormSettings, queue_capacity: int) -> None:
        self._config = config
        self._capacity = max(queue_capacity, 1)
        self._in_storm = False
        self._started_at: datetime | None = None
        self._ended_at: datetime | None = None
        self._trigger_rate = _RateTracker(config.trigger_signal_rate_window_sec)
        self._recovery_rate = _RateTracker(config.recovery_signal_rate_window_sec)
        self._low_depth_since: datetime | None = None
        self._high_depth_since: datetime | None = None

    @property
    def in_storm(self) -> bool:
        return self._in_storm

    def update(
        self,
        *,
        raw_signals_this_tick: int,
        queue_depth: int,
        now: datetime,
    ) -> StormState:
        self._trigger_rate.observe(now, raw_signals_this_tick)
        self._recovery_rate.observe(now, raw_signals_this_tick)
        depth_pct = queue_depth / self._capacity
        if not self._in_storm:
            rate_exceeded = (
                self._trigger_rate.rate_per_second() > self._config.trigger_signal_rate_per_sec
            )
            depth_exceeded = depth_pct > self._config.trigger_queue_depth_pct
            # Depth trigger requires sustainment per
            # docs/architecture/deduplication-and-storms.md §Storm Detection.
            if depth_exceeded:
                if self._high_depth_since is None:
                    self._high_depth_since = now
                sustained = (
                    now - self._high_depth_since
                ).total_seconds() >= self._config.trigger_queue_depth_window_sec
            else:
                self._high_depth_since = None
                sustained = False
            if rate_exceeded or sustained:
                self._enter_storm(now)
        else:
            rate_low = (
                self._recovery_rate.rate_per_second() < self._config.recovery_signal_rate_per_sec
            )
            depth_low = depth_pct < self._config.recovery_queue_depth_pct
            if rate_low and depth_low:
                if self._low_depth_since is None:
                    self._low_depth_since = now
                elapsed = (now - self._low_depth_since).total_seconds()
                if elapsed >= self._config.recovery_queue_depth_window_sec:
                    self._exit_storm(now)
            else:
                self._low_depth_since = None
        return StormState(
            in_storm=self._in_storm,
            started_at=self._started_at,
            ended_at=self._ended_at,
        )

    def _enter_storm(self, now: datetime) -> None:
        self._in_storm = True
        self._started_at = now
        self._ended_at = None
        self._low_depth_since = None
        self._high_depth_since = None

    def _exit_storm(self, now: datetime) -> None:
        self._in_storm = False
        self._ended_at = now
        self._low_depth_since = None
        self._high_depth_since = None


DropPolicy = Literal["lifo", "reject"]
