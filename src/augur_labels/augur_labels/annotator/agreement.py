"""Inter-annotator agreement metrics.

Implements Cohen's kappa, 60-second timestamp agreement, and mean
Jaccard overlap of market-association sets per the targets in
docs/methodology/labeling-protocol.md §Inter-Annotator Agreement.

Paired decisions are matched by ``candidate_id``; decisions on
candidates only one annotator reviewed are excluded from the report.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from augur_labels.models import AgreementReport, LabelDecision

# Thresholds mirror labeling-protocol.md §Inter-Annotator Agreement.
EVENT_EXISTENCE_KAPPA_TARGET: float = 0.95
TIMESTAMP_AGREEMENT_TARGET: float = 0.90
MARKET_JACCARD_TARGET: float = 0.85
CATEGORY_KAPPA_TARGET: float = 0.90
TIMESTAMP_AGREEMENT_WINDOW: timedelta = timedelta(seconds=60)


def _cohens_kappa(labels_a: Sequence[object], labels_b: Sequence[object]) -> float:
    """Cohen's kappa on two equal-length sequences of categorical labels.

    Raises ValueError on length mismatch so a data-integrity bug in the
    caller surfaces immediately rather than masquerading as low kappa.
    Empty inputs short-circuit to 0.0 because an empty window has no
    meaningful agreement metric.
    """
    if len(labels_a) != len(labels_b):
        raise ValueError(
            f"label sequences have mismatched lengths: {len(labels_a)} vs {len(labels_b)}"
        )
    if not labels_a:
        return 0.0
    n = len(labels_a)
    observed = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b) / n
    all_labels = set(labels_a) | set(labels_b)
    expected = 0.0
    for label in all_labels:
        pa = sum(1 for x in labels_a if x == label) / n
        pb = sum(1 for x in labels_b if x == label) / n
        expected += pa * pb
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


def _pair_decisions(
    decisions_a: Sequence[LabelDecision],
    decisions_b: Sequence[LabelDecision],
) -> tuple[list[tuple[LabelDecision, LabelDecision]], int]:
    """Return (paired_decisions, unpaired_count).

    Unpaired decisions (candidate reviewed by only one annotator) are
    surfaced so ``compute_agreement`` can report them without silently
    dropping from the denominator.
    """
    by_candidate_a = {d.candidate_id: d for d in decisions_a}
    by_candidate_b = {d.candidate_id: d for d in decisions_b}
    shared = set(by_candidate_a) & set(by_candidate_b)
    unpaired = len(set(by_candidate_a) ^ set(by_candidate_b))
    return [(by_candidate_a[c], by_candidate_b[c]) for c in sorted(shared)], unpaired


def compute_agreement(
    decisions_a: Sequence[LabelDecision],
    decisions_b: Sequence[LabelDecision],
    window_start: datetime,
    window_end: datetime,
) -> AgreementReport:
    """Compute the four-metric report for paired decisions."""
    pairs, unpaired = _pair_decisions(decisions_a, decisions_b)
    annotator_ids = (
        tuple(sorted({decisions_a[0].annotator_id, decisions_b[0].annotator_id}))
        if decisions_a and decisions_b
        else ("unknown-a", "unknown-b")
    )
    if not pairs:
        return AgreementReport(
            annotator_pair=annotator_ids,  # type: ignore[arg-type]
            window_start=window_start,
            window_end=window_end,
            candidate_count=0,
            unpaired_count=unpaired,
            event_existence_kappa=0.0,
            timestamp_agreement_60s=0.0,
            market_association_jaccard_mean=0.0,
            category_assignment_kappa=0.0,
            meets_targets=False,
        )
    qualifies_a = [a.qualifies for a, _ in pairs]
    qualifies_b = [b.qualifies for _, b in pairs]
    event_kappa = _cohens_kappa(qualifies_a, qualifies_b)

    # Timestamp agreement: only paired qualifying decisions contribute.
    qualifying_pairs = [
        (a, b) for a, b in pairs if a.qualifies and b.qualifies and a.timestamp and b.timestamp
    ]
    if qualifying_pairs:
        within = 0
        threshold = TIMESTAMP_AGREEMENT_WINDOW.total_seconds()
        for a, b in qualifying_pairs:
            ts_a = a.timestamp
            ts_b = b.timestamp
            if ts_a is None or ts_b is None:
                continue
            if abs((ts_a - ts_b).total_seconds()) <= threshold:
                within += 1
        timestamp_agreement = within / len(qualifying_pairs)
    else:
        timestamp_agreement = 0.0

    # Market Jaccard — mean across paired qualifying decisions.
    if qualifying_pairs:
        jaccards = [_jaccard(a.market_ids, b.market_ids) for a, b in qualifying_pairs]
        jaccard_mean = sum(jaccards) / len(jaccards)
    else:
        jaccard_mean = 0.0

    # Category kappa — pairs with both categories set.
    category_pairs = [(a.category, b.category) for a, b in pairs if a.category and b.category]
    if category_pairs:
        category_kappa = _cohens_kappa(
            [p[0] for p in category_pairs], [p[1] for p in category_pairs]
        )
    else:
        category_kappa = 0.0

    meets_targets = (
        event_kappa >= EVENT_EXISTENCE_KAPPA_TARGET
        and timestamp_agreement >= TIMESTAMP_AGREEMENT_TARGET
        and jaccard_mean >= MARKET_JACCARD_TARGET
        and category_kappa >= CATEGORY_KAPPA_TARGET
    )
    return AgreementReport(
        annotator_pair=annotator_ids,  # type: ignore[arg-type]
        window_start=window_start,
        window_end=window_end,
        candidate_count=len(pairs),
        unpaired_count=unpaired,
        event_existence_kappa=event_kappa,
        timestamp_agreement_60s=timestamp_agreement,
        market_association_jaccard_mean=jaccard_mean,
        category_assignment_kappa=category_kappa,
        meets_targets=meets_targets,
    )
