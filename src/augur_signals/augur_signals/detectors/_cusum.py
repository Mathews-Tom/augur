"""Two-sided CUSUM for detecting sustained shifts in a running mean.

Standard formulation: maintain positive and negative cumulative sums,
reset when they cross a control threshold `h * sigma`. `k` is the
allowable slack below which no accumulation happens; together `(k, h)`
trade off detection speed against false-positive rate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TwoSidedCUSUM:
    """Per-market positive/negative CUSUM pair."""

    k_sigma: float
    h_sigma: float
    sigma_estimate: float = 1.0
    positive: float = 0.0
    negative: float = 0.0
    samples: int = 0
    mean_estimate: float = 0.0
    _m2: float = 0.0

    def update(self, observation: float) -> tuple[float, float]:
        """Apply one observation; return the current (positive, negative) pair."""
        self.samples += 1
        delta = observation - self.mean_estimate
        self.mean_estimate += delta / self.samples
        delta2 = observation - self.mean_estimate
        self._m2 += delta * delta2
        if self.samples > 1:
            self.sigma_estimate = max(1e-9, (self._m2 / (self.samples - 1)) ** 0.5)
        k = self.k_sigma * self.sigma_estimate
        self.positive = max(0.0, self.positive + (observation - self.mean_estimate) - k)
        self.negative = min(0.0, self.negative + (observation - self.mean_estimate) + k)
        return self.positive, self.negative

    def threshold(self) -> float:
        return self.h_sigma * self.sigma_estimate

    def reset(self) -> None:
        self.positive = 0.0
        self.negative = 0.0
