# Labeling Protocol

This document defines the operational rules for building Augur's labeled corpus of newsworthy events. The corpus is the empirical foundation for confidence calibration, FDR threshold derivation, and reliability-curve construction. Without the corpus, every claim Augur makes about precision is undefined.

## Definition of a Newsworthy Event

A newsworthy event is a real-world occurrence reported by at least two independent qualifying sources within a 24-hour window. The qualifying source set at protocol version 1.0 is:

| Source           | Rationale                                                               |
| ---------------- | ----------------------------------------------------------------------- |
| Reuters          | Wire service with editorial standards and global coverage.              |
| Bloomberg        | Financial wire with deep markets and macro coverage.                    |
| Associated Press | General news wire with editorial standards and broad topical coverage.  |
| Financial Times  | Editorially independent financial publication with international scope. |

The two-source requirement filters single-publication errors and rumor-stage reporting. The 24-hour window captures the reasonable lead-time horizon Augur targets without admitting trailing-coverage artifacts as new events.

This definition is operational, not philosophical. Events that "should be" newsworthy but were not picked up by qualifying sources are not labeled. The protocol prefers underlabeling over hallucinated labels.

## Source Hierarchy and Ordering

When labeling an event, sources are inspected in publication-timestamp order. The earliest qualifying publication establishes the event's `ground_truth_timestamp`. Subsequent qualifying publications confirm the event but do not change the timestamp.

If only one qualifying source publishes within the 24-hour window, the event is held in a "candidate" state for an additional 24 hours. If a second qualifying source publishes within that window, the event is promoted to "labeled" with the timestamp of the first publication. If no second source publishes, the event is dropped from the corpus.

## Ground-Truth Timestamp Rule

```
event.ground_truth_timestamp = earliest_qualifying_publication.timestamp
```

Timestamps are stored in UTC with second precision. Sub-second precision is not required because Augur's polling cadence floors at 15 seconds.

## Lead-Time Computation

For each `MarketSignal`, lead time is computed against any associated event:

```
lead_time(signal, event) = event.ground_truth_timestamp - signal.detected_at
```

Lead time is positive when the signal preceded the event publication and negative when the signal followed it.

## True Positive Criteria

A signal is a true positive against an event if and only if:

1. `signal.market_id` is in `event.market_ids` (the event labeling associates the event with one or more markets).
2. `lead_time(signal, event) ∈ (0, 24 hours]`. Signals more than 24 hours ahead are treated as coincidental, not predictive. Signals at or after the event are reactive, not predictive.

A signal is a false positive if it does not match any event by the above criteria within the lead-time window. A signal is a true negative if no signal fires on a market during a window in which no event occurred.

## Event-to-Market Association

When a labeler processes a candidate event, they associate it with one or more `market_id` values from the curated watchlist. Association rules:

1. The event must be directly relevant to the market's resolution criteria. A Federal Reserve rate decision is associated with rate-decision markets, not with general "macro" markets.
2. Cross-market associations are explicit. An event affecting multiple markets (e.g., a major Fed action affects rate, inflation, and unemployment markets) is associated with each market in the relevant set.
3. Indirect or speculative associations are rejected. The labeler errs toward fewer associations rather than overreaching.

## Annotator Protocol

Labelers follow a fixed protocol per candidate event:

1. **Source verification.** Confirm the event is published by at least two qualifying sources within the 24-hour window.
2. **Timestamp extraction.** Record the earliest qualifying publication timestamp in UTC.
3. **Market association.** Identify all watchlist markets directly tied to the event's resolution criteria.
4. **Category assignment.** Assign a market category from the closed list in `../contracts/consumer-registry.md` routing table.
5. **Storage.** Append the event to `labels/newsworthy_events.parquet` with the schema defined below.
6. **Audit trail.** Record the labeler's identity, the source URLs verified, and the protocol version.

Labelers do not edit existing events. Corrections are made by appending a corrected event with a `corrects` reference to the original event ID and the original event marked `superseded`.

## Inter-Annotator Agreement

The corpus is doubly labeled for the first 90 days of operation. Two annotators independently label each candidate event. Agreement is measured on:

| Metric                                                              | Target               |
| ------------------------------------------------------------------- | -------------------- |
| Event existence (does the candidate qualify?)                       | ≥ 0.95 Cohen's kappa |
| Timestamp agreement (within 60 seconds)                             | ≥ 0.90               |
| Market association (Jaccard overlap of associated `market_id` sets) | ≥ 0.85               |
| Category assignment                                                 | ≥ 0.90 Cohen's kappa |

Disagreements are escalated to a third annotator for tie-breaking. After 90 days of meeting targets, single labeling is permitted with periodic spot audits.

## Storage Schema

The labeled corpus is stored as Parquet at `labels/newsworthy_events.parquet`:

| Column                   | Type           | Description                                             |
| ------------------------ | -------------- | ------------------------------------------------------- |
| `event_id`               | string (uuid7) | Stable identifier                                       |
| `ground_truth_timestamp` | timestamp UTC  | Earliest qualifying publication time                    |
| `market_ids`             | list[string]   | Associated watchlist markets                            |
| `category`               | string         | Market category from routing table                      |
| `headline`               | string         | Verbatim from earliest qualifying publication           |
| `source_urls`            | list[string]   | URLs of all qualifying publications used                |
| `source_publishers`      | list[string]   | Publisher names matching `source_urls`                  |
| `labeler_ids`            | list[string]   | Annotator identifiers                                   |
| `label_protocol_version` | string         | Semver of the protocol at labeling time                 |
| `corrects`               | string         | Optional reference to a superseded `event_id`           |
| `status`                 | string         | One of `labeled`, `candidate`, `superseded`, `rejected` |
| `created_at`             | timestamp UTC  | Labeling time                                           |

The corpus is append-only. Edits create new rows with `corrects` pointing at the original; the original's `status` is updated to `superseded` only via append operations using the table-level overwrite mechanism.

## Versioning

Every label carries `label_protocol_version`. This document is at version 1.0. Changes to:

- The qualifying source set
- The two-source requirement
- The 24-hour window
- The lead-time true-positive window
- The market association rules
- The annotator workflow

require a protocol version bump and a recomputation of any calibration metrics derived from the affected labels. Protocol changes are tracked in a `CHANGELOG.md` alongside the corpus.

## Known Limitations

The protocol has the following limits, which calibration consumers must understand:

1. **Source bias.** The qualifying source set is heavily Anglosphere and finance-tilted. Events well-covered by non-English-language press but ignored by the qualifying sources do not enter the corpus. This biases calibration toward markets whose underlying events are likely to appear in the qualifying sources — primarily US politics, US macroeconomics, major crypto, and certain geopolitical events. Coverage of events outside these clusters is structurally weaker.
2. **Editorial latency.** Wire services have varying editorial review processes. The earliest qualifying timestamp may be slightly delayed relative to the underlying event. The 24-hour true-positive window is calibrated to absorb this, but tighter lead-time analyses (e.g., sub-hour) are unreliable.
3. **No private-information labels.** The corpus only captures publicly reported events. Genuinely informed trading on private information that never surfaces publicly is not labeled and produces a permanent gap in calibration.
4. **Resolution-driven labels are excluded.** Market resolution events themselves are not labeled as newsworthy unless an independent reporting event corresponds to them. A market resolving to YES is not the news; the underlying event is.
5. **Backfill is not retroactive.** Adding a new qualifying source to a future protocol version does not retroactively relabel old events. Calibration mixing pre- and post-bump labels is invalid.

The protocol's limits are inherited by every confidence value Augur produces. Consumers using `MarketSignal.confidence` for high-stakes decisions should review this section.
