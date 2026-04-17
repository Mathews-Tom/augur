# Calibration Methodology

This document defines how Augur converts raw detector outputs into the empirical `confidence` value that appears on every `MarketSignal`. The methodology applies uniformly to all detectors. The calibration layer is mandatory; signals emitted without a calibration provenance stamp are rejected at the schema boundary.

## Why Raw Detector Scores Are Not Confidence

Each detector produces a raw score: a BOCPD posterior probability, a z-score, a CUSUM statistic, a Spearman z-distance with a Benjamini-Hochberg-adjusted p-value. These scores measure model fit — how well the observation deviates from the detector's null hypothesis under its assumed distribution. They do not measure predictive validity. A BOCPD posterior of 0.95 on a market with skewed marginals near a price boundary is not 95% likely to correspond to a true changepoint.

Calibrated confidence is a different quantity: the empirically observed fraction of signals at this raw score that turned out to be true positives in held-out labeled data. The two values can diverge substantially. Without calibration, downstream consumers receive overconfident signals and learn to ignore the feed.

## Pipeline

```text
raw detector score
        │
        ▼
  per-detector reliability curve
        │
        ▼
  empirical confidence in [0, 1]
        │
        ▼
  attached to MarketSignal.confidence
        │
        ▼
  raw score retained in raw_features for diagnostics
```

The calibration layer never modifies a signal's classification (fired or not). It only assigns the `confidence` field. Detectors decide whether to fire; the calibration layer decides how confident the system is in that firing.

## Empirical False-Positive Rate Computation

For each `(detector_id, market_id)` pair, the empirical FPR is computed nightly:

```text
FPR = false_positives / (false_positives + true_negatives)
```

over the prior 30 days of detector output, where true positives and false positives are defined against the labeled `NewsworthyEvent` corpus per `./labeling-protocol.md`.

The result is stored in the `calibration_fpr` table:

| Column                   | Type      |
| ------------------------ | --------- |
| `detector_id`            | varchar   |
| `market_id`              | varchar   |
| `fpr`                    | double    |
| `sample_size`            | integer   |
| `computed_at`            | timestamp |
| `label_protocol_version` | varchar   |

Markets with sample size below 100 fall back to the per-detector aggregate FPR rather than the per-market value, to avoid over-fitting to thin data.

## Benjamini-Hochberg FDR Control

Two detectors emit batches of candidate signals per polling cycle: the volume spike detector (one candidate per market) and the cross-market divergence detector (one candidate per related-market pair). For each batch:

1. Each candidate is associated with a p-value computed under the detector's null model.
2. Candidates are sorted ascending by p-value: `p_(1) ≤ p_(2) ≤ ... ≤ p_(m)`.
3. The largest `k` such that `p_(k) ≤ (k/m) * q` is found, where `q` is the target FDR (default 0.05).
4. The first `k` candidates are emitted with `fdr_adjusted = true`. Remaining candidates are suppressed.

The shared `FDRController` service maintains the per-detector target `q`, exposes the current passing-threshold to detectors, and accepts batched p-value submissions. A detector that bypasses the controller produces signals with `fdr_adjusted = false`, which fail validation and are rejected at the schema boundary.

## Reliability Curve Construction

For each detector, a reliability curve is built from the prior 30 days of (raw_score, label) pairs:

1. Bin signals into deciles by raw score.
2. For each decile, compute the mean raw score and the observed precision (true positives / total signals in decile).
3. The pairs (mean_raw_score, observed_precision) form the reliability curve.
4. The curve is monotone-regularized using isotonic regression to enforce the property that higher raw scores yield higher calibrated confidence.

A new signal is calibrated by linear interpolation between the two nearest decile midpoints. Signals outside the observed score range are clipped to the nearest decile midpoint's confidence.

The curve is stored per detector with a `curve_version` identifier; the version is recorded in `MarketSignal.raw_features["calibration_provenance"]`.

## PSI and KS Drift Monitoring

Calibration validity depends on the distribution of raw scores remaining stationary. When new markets are added, when platform participant mixes change, or when external regimes shift, the score distribution can drift in ways that invalidate the reliability curve.

Two monitors run nightly:

| Monitor                    | Statistic                                                                                            | Trigger Threshold |
| -------------------------- | ---------------------------------------------------------------------------------------------------- | ----------------- |
| Population Stability Index | PSI on the raw-score distribution between the prior 30-day baseline and the most recent 7-day window | PSI > 0.2         |
| Kolmogorov-Smirnov         | KS test on the same windows                                                                          | p-value < 0.01    |

A trigger emits a `CalibrationStaleEvent` to the operations channel. The Phase 1 action is alert-only; recalibration is a manual operator decision. Automated recalibration is deferred per the migration triggers in `../architecture/storage-and-scaling.md`.

## Liquidity-Tier Banding

Calibration is conditioned on liquidity tier. The same raw BOCPD posterior on a high-tier market (≥ $250,000 daily volume) and a low-tier market ($10,000 to $50,000 daily volume) produces different calibrated confidences, because the empirical precision differs by an order of magnitude. Tier boundaries are defined in `../foundations/glossary.md`. Tier-conditional reliability curves are stored separately.

Markets below the low-tier floor ($10,000 daily volume) are excluded from the watchlist — no signals are produced for them and no calibration is computed.

## Recalibration Cadence

| Trigger                       | Action                                                                                                               |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Nightly cron                  | Recompute empirical FPR per detector and per market; rebuild reliability curves.                                     |
| New market added to watchlist | Defer signal emission for 7 days while baseline accumulates; use per-detector aggregate calibration in the interim.  |
| Drift monitor trigger         | Operator decision: accept stale calibration with a logged warning, or recalibrate against a shorter trailing window. |
| Schema major version bump     | Full recalibration on the new schema; no carry-over of old curves.                                                   |

## How Consumers Should Use `confidence`

The `confidence` field is a probability — the empirical fraction of similarly-scored signals in the labeled corpus that were true positives. Consumers should treat it as such:

- A consumer that wants to see the top decile of signals filters on `confidence ≥ 0.9`. This corresponds to roughly a 90% precision in the reference labeling protocol.
- A consumer that wants to see all signals can ignore `confidence` and use only the binary `fdr_adjusted` field plus their own thresholding.
- A consumer should not interpret `confidence` as a probability that the underlying real-world event will occur. Augur does not make claims about events; it makes claims about the precision of its own signals.

`confidence` is conditional on the labeling protocol. A consumer using Augur in a domain where "newsworthy" is defined differently from the protocol in `./labeling-protocol.md` should not expect the calibration to transfer; they should compute their own per-consumer reliability curves on their own labels.

## Forbidden Causal Vocabulary (LLM Formatter Constraint)

The optional LLM formatter (gated, opt-in) enforces a forbidden-token check on every brief before emission. The check rejects briefs containing standard causal-narrative phrase patterns that convert a price delta into a causal claim Augur cannot back. The pattern categories are:

| Category                             | Pattern Shape                                                                                                                                       |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Modal causation                      | A modal verb followed by a causation verb (e.g., the modal-causation construction asserting that an outcome `was caused by` an unspecified factor). |
| Coherence-with-information assertion | Phrases asserting that a price move is consistent with the arrival of new information.                                                              |
| Probabilistic indication             | Phrases asserting that an observation indicates an unobserved cause.                                                                                |
| Reflective causation                 | Phrases asserting that a price move reflects an underlying state change.                                                                            |
| Hedged suggestion                    | Phrases that suggest a causal mechanism without committing to it.                                                                                   |

The exact list of rejected phrase strings lives in the implementation's linter configuration (`config/forbidden_tokens.toml`), not in this document. Maintaining the canonical list in code rather than prose prevents the documentation itself from triggering the same lint that protects the LLM output. The list is closed at schema 1.0.0; additions require a schema version bump and a recalibration of any briefs produced under the old list.

A brief containing any rejected phrase is dropped at the formatter boundary and an error is logged. Consumers expecting causal interpretation should produce it themselves from the structured `SignalContext`, not consume LLM-generated narrative as fact.

## Worked Example: Raw BOCPD Posterior to Calibrated Confidence

Suppose a price velocity signal fires on a high-tier macro market with raw posterior `P(r_t < 5 | data) = 0.92`.

1. The detector sets `magnitude = 0.92`, `direction = +1`, `fdr_adjusted = true` (this detector does not require BH).
2. The calibration layer looks up the high-tier reliability curve for `price_velocity_bocpd_beta_v1`.
3. The curve maps raw scores in the 0.90 decile (mean 0.93) to observed precision 0.71 in the prior 30 days.
4. Linear interpolation gives calibrated `confidence = 0.71`.
5. The signal is emitted with `confidence = 0.71`, `raw_features = {"posterior_p_change": 0.92, "calibration_provenance": "price_velocity_bocpd_beta_v1@curve_v1.3"}`.

The 0.92 raw posterior reflected model fit; the 0.71 calibrated confidence reflects predictive validity in held-out data. A consumer comparing the two values can immediately see that the model is more confident than the data justifies, which is the expected gap for BOCPD on bounded-domain series even with the Beta-Binomial observation model.
