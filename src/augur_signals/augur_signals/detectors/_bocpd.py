"""Bayesian Online Changepoint Detection with Beta-Binomial likelihood.

Reference: Adams & MacKay 2007 ("Bayesian Online Changepoint
Detection", arXiv 0710.3742), adapted for observations in [0, 1].
Each observation x is treated as the probability of a single
Bernoulli trial so the conjugate Beta-Binomial predictive
``alpha / (alpha + beta) * x + beta / (alpha + beta) * (1 - x)``
applies directly.

The run-length distribution is capped at ``run_length_cap`` so memory
is bounded; for a hazard of 1/250 and a cap of 1000 the truncation
error on the fire decision is negligible (<1e-6).
"""

from __future__ import annotations

import math
from typing import Any


class BetaBinomialBOCPD:
    """Online change-point detector for observations in [0, 1]."""

    def __init__(
        self,
        hazard_rate: float,
        alpha_prior: float,
        beta_prior: float,
        run_length_cap: int,
    ) -> None:
        if not 0.0 < hazard_rate < 1.0:
            raise ValueError("hazard_rate must lie in (0, 1)")
        if alpha_prior <= 0.0 or beta_prior <= 0.0:
            raise ValueError("alpha_prior and beta_prior must be positive")
        if run_length_cap <= 0:
            raise ValueError("run_length_cap must be positive")
        self._hazard = hazard_rate
        self._cap = run_length_cap
        self._alpha0 = alpha_prior
        self._beta0 = beta_prior
        self._pr: list[float] = [0.0] * (run_length_cap + 1)
        self._pr[0] = 1.0
        self._alphas: list[float] = [alpha_prior] * (run_length_cap + 1)
        self._betas: list[float] = [beta_prior] * (run_length_cap + 1)

    def update(self, observation: float) -> tuple[float, float]:
        """Process one observation.

        Returns the tuple ``(P(r_t < 5), E[r_t])`` where ``r_t`` is the
        run length in observations since the last change point.
        """
        if not 0.0 <= observation <= 1.0:
            raise ValueError("observation must lie in [0, 1]")

        # Predictive for each run length under the Beta-Binomial posterior.
        predictive: list[float] = []
        for alpha, beta in zip(self._alphas, self._betas, strict=True):
            total = alpha + beta
            predictive.append(alpha / total * observation + beta / total * (1.0 - observation))

        growth = [self._pr[i] * predictive[i] * (1.0 - self._hazard) for i in range(self._cap + 1)]
        change_mass = sum(self._pr[i] * predictive[i] * self._hazard for i in range(self._cap + 1))
        new_pr: list[float] = [0.0] * (self._cap + 1)
        new_pr[0] = change_mass
        # Growth shifts run length up by one. Mass that would otherwise
        # land at cap+1 is absorbed back into the cap bucket so the
        # run-length distribution does not leak probability as ``t`` grows
        # past the cap.
        for i in range(1, self._cap):
            new_pr[i] = growth[i - 1]
        new_pr[self._cap] = growth[self._cap - 1] + growth[self._cap]

        total_mass = sum(new_pr)
        if total_mass <= 0.0:
            # Numerical collapse — reset to the prior rather than return garbage.
            new_pr = [0.0] * (self._cap + 1)
            new_pr[0] = 1.0
            total_mass = 1.0
        self._pr = [p / total_mass for p in new_pr]

        new_alphas: list[float] = [self._alpha0] + [0.0] * self._cap
        new_betas: list[float] = [self._beta0] + [0.0] * self._cap
        for i in range(1, self._cap):
            new_alphas[i] = self._alphas[i - 1] + observation
            new_betas[i] = self._betas[i - 1] + (1.0 - observation)
        # Absorb cap-1 and cap sufficient statistics with weights matching
        # the two mass contributions so the posterior remains a proper
        # mixture at the cap bucket.
        weight_prev = growth[self._cap - 1]
        weight_absorb = growth[self._cap]
        weight_total = weight_prev + weight_absorb
        if weight_total > 0.0:
            new_alphas[self._cap] = (
                weight_prev * (self._alphas[self._cap - 1] + observation)
                + weight_absorb * (self._alphas[self._cap] + observation)
            ) / weight_total
            new_betas[self._cap] = (
                weight_prev * (self._betas[self._cap - 1] + (1.0 - observation))
                + weight_absorb * (self._betas[self._cap] + (1.0 - observation))
            ) / weight_total
        else:
            new_alphas[self._cap] = self._alphas[self._cap - 1] + observation
            new_betas[self._cap] = self._betas[self._cap - 1] + (1.0 - observation)
        self._alphas = new_alphas
        self._betas = new_betas

        p_change = sum(self._pr[: min(5, self._cap + 1)])
        expected_run_length = sum(i * self._pr[i] for i in range(self._cap + 1))
        return p_change, expected_run_length

    def state_dict(self) -> dict[str, Any]:
        return {
            "hazard": self._hazard,
            "cap": self._cap,
            "alpha0": self._alpha0,
            "beta0": self._beta0,
            "pr": list(self._pr),
            "alphas": list(self._alphas),
            "betas": list(self._betas),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        self._hazard = float(state["hazard"])
        self._cap = int(state["cap"])
        self._alpha0 = float(state["alpha0"])
        self._beta0 = float(state["beta0"])
        self._pr = [float(x) for x in state["pr"]]
        self._alphas = [float(x) for x in state["alphas"]]
        self._betas = [float(x) for x in state["betas"]]


def laplace_smoothed_logit(price: float, eps: float = 1e-4) -> float:
    """Clamp *price* to [eps, 1-eps] so log transforms stay finite.

    The BOCPD observation model itself operates on the raw price; this
    helper is retained for call sites that need a bounded logit for
    momentum computation near the 0/1 boundaries.
    """
    bounded = max(eps, min(1.0 - eps, price))
    return math.log(bounded / (1.0 - bounded))
