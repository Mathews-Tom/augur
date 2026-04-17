"""Consumer gate enforcing opt-in for llm_assisted briefs.

Per docs/contracts/consumer-registry.md, only consumers whose
configuration sets ``accepts_llm_assisted = true`` receive LLM-
rendered briefs. The deterministic JSON and Markdown briefs from
Phase 3 still reach every consumer; the gate only filters the LLM
output.
"""

from __future__ import annotations

from collections.abc import Iterable

from augur_format.llm.models import IntelligenceBrief
from augur_signals.models import ConsumerType


class ConsumerGate:
    """Filters consumer sets by accepts_llm_assisted opt-in."""

    def __init__(self, opted_in: Iterable[ConsumerType]) -> None:
        self._opted_in = frozenset(opted_in)

    @property
    def opted_in(self) -> frozenset[ConsumerType]:
        return self._opted_in

    def is_eligible(self, consumer: ConsumerType, brief: IntelligenceBrief) -> bool:
        """True iff *consumer* has opted in to LLM-assisted briefs."""
        del brief  # brief identity does not factor into the gate decision.
        return consumer in self._opted_in

    def filter_consumers(
        self, consumers: Iterable[ConsumerType], brief: IntelligenceBrief
    ) -> list[ConsumerType]:
        """Return the subset of consumers eligible for this brief."""
        return [c for c in consumers if self.is_eligible(c, brief)]
