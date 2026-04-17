# Negative-Path Examples

Concrete examples of how Augur fails or produces output that should be treated cautiously. These are first-class artifacts: a system that publishes only its successes is not credible. Each example shows the failure mode, the symptom Augur produces, the recommended consumer mitigation, and the residual risk that no mitigation eliminates.

---

## Example 1 — Manipulation-Driven Signal Storm

### Scenario

A coordinated buyer executes a series of large trades on the Polymarket contract `polymarket_corp_scandal_x` ("Will Company X face SEC enforcement action by Q3 2026?"), pushing the price from 0.30 to 0.48 over four polling cycles (two minutes). The contract is in the `mid` liquidity tier ($60K daily volume). The buyer's trades consume 35% to 50% of resting depth on each fill.

### Detection

The price velocity detector fires. The volume spike detector fires. The manipulation detector evaluates and matches three signatures: `single_counterparty_concentration`, `size_vs_depth_outlier`, and `thin_book_during_move`. The signal is emitted with the flags attached.

### Symptom (Signal As Emitted)

```json
{
  "signal_id": "01HX5A2GNVJ7C2KP9XHTKP4M3F",
  "market_id": "polymarket_corp_scandal_x",
  "platform": "polymarket",
  "signal_type": "price_velocity",
  "magnitude": 0.81,
  "direction": 1,
  "confidence": 0.43,
  "fdr_adjusted": true,
  "detected_at": "2026-04-16T14:02:00Z",
  "window_seconds": 120,
  "liquidity_tier": "mid",
  "manipulation_flags": [
    "single_counterparty_concentration",
    "size_vs_depth_outlier",
    "thin_book_during_move"
  ],
  "related_market_ids": [],
  "raw_features": {
    "drift_pct": 0.18,
    "herfindahl": 0.71,
    "max_size_vs_depth": 0.48,
    "median_depth_during_move": 4200.0,
    "calibration_provenance": "price_velocity_bocpd_beta_v1@curve_v1.3"
  },
  "schema_version": "1.0.0"
}
```

Note that `confidence` is 0.43 — much lower than a comparable clean signal would receive. The calibration layer's per-market FPR for this contract reflects historical noise; combined with the manipulation flags, the confidence is correctly suppressed below the typical "high-precision" band.

### Consumer Mitigation

| Consumer                | Recommended Behavior                                                                                                                                                                                      |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `financial_news_desk`   | Default suppression policy excludes signals with `single_counterparty_concentration`. Brief is dropped before reaching the desk.                                                                          |
| `regulatory_news_desk`  | Default suppression policy does not exclude this combination, but the desk's editorial workflow requires independent verification before any publication; the verification step exposes the manipulation. |
| `crypto_research_agent` | Receives the brief intentionally; investigates the trade pattern as a potential manipulation incident.                                                                                                    |
| `dashboard`             | Receives and visually badges the brief with the manipulation flags; human reader sees the warning.                                                                                                        |

The investigation prompts in the `SignalContext` for this signal type include "Check whether any single counterparty contributed disproportionately to the move," which directly surfaces the manipulation pattern to the agent that does receive the brief.

### Residual Risk

Manipulation detection is conservative. Sophisticated manipulators avoiding the obvious patterns (using multiple wallets, splitting trades across longer windows, choosing depth ratios just below the threshold) can produce signals with empty `manipulation_flags`. The calibration layer's per-market FPR catches some of this through reduced confidence, but the residual is real.

A consumer that ignores the calibration `confidence` field and treats every signal as authoritative will be exposed.

---

## Example 2 — Black-Swan Event With No Pre-Existing Market

### Scenario

On a Saturday morning, a major payment-processing network suffers a multi-hour outage caused by a previously undisclosed cyberattack. Reuters publishes the first wire story at 11:14 UTC. There is no Polymarket or Kalshi contract on this specific event, and no closely related contract has detectable price movement before the news breaks.

### Detection

Augur produces zero signals before 11:14 UTC. After the news breaks, related markets do react: a `kalshi_payments_volume_2026` contract drops 4 points; a `polymarket_cybersec_indicator` contract rises 3 points. Both moves are below the FDR-controlled thresholds for their respective detectors and do not produce signals.

### Symptom

Augur's feed shows no event corresponding to the cyberattack. A consumer monitoring the feed sees normal Saturday-low-activity output.

### Consumer Mitigation

This is the expected behavior, not a failure to mitigate. The non-goals document explicitly states that Augur does not detect events for which no market exists. A consumer who treats the absence of an Augur signal as confirmation that nothing is happening has misread the documentation.

The mitigation is consumer literacy:

- The `dashboard` consumer renders an explicit "no recent signals" indicator with a timestamp; this is informational, not reassurance.
- The `regulatory_news_desk` and `financial_news_desk` consumers do not rely on Augur's silence as a clear-channel signal; their primary news sources cover events Augur cannot.
- Agent consumers' integration documentation states that Augur is one input among several and silence on Augur means "no qualifying market signal," not "no event."

### Residual Risk

A new consumer integrating against Augur for the first time may infer over-reach from the marketing material. The non-goals document and the introduction in `../foundations/overview.md` are the primary defense; a consumer who reads neither is not Augur's typical audience but the misuse risk persists.

---

## Example 3 — Calibration Collapse on Regime Change

### Scenario

Kalshi adds 30 new contract categories in a single quarter following a CFTC clarification expanding event-contract definitions. The new contracts have different participant mixes (more institutional, fewer retail) than the contracts on which Augur's reliability curves were trained. Detector raw scores remain in the same numerical range, but the empirical precision of those scores on the new contracts is markedly different.

### Detection

The drift monitor in the calibration layer fires:

- PSI on `volume_spike_fdr_v1` raw score distribution: 0.27 (above 0.2 threshold).
- KS test p-value on `price_velocity_bocpd_beta_v1`: 0.003 (below 0.01 threshold).

A `CalibrationStaleEvent` is emitted to the operations channel. The operator is paged.

### Symptom

Until the operator acts, signals continue to emit with their old calibrated confidence. The `confidence` field is now systematically wrong — likely overconfident on the new contracts and possibly miscalibrated on the originals.

### Consumer Mitigation

Consumers cannot directly mitigate. The operator's response is the mitigation:

1. Operator inspects which detector and which markets are driving the drift.
2. Operator decides between two options: (a) recalibrate against a shorter trailing window that includes the new contracts; (b) hold calibration constant and add a `calibration_stale: true` warning to affected signals.
3. If recalibration is chosen, new reliability curves are built and the operator confirms the drift monitors return to nominal.
4. If hold is chosen, consumer-facing documentation is updated to note the affected markets carry stale calibration until resolved.

The drift monitor exists precisely because this scenario is foreseeable; the alert is the system functioning correctly.

### Residual Risk

The drift monitor's PSI and KS thresholds are themselves heuristics. A drift below the thresholds (PSI = 0.18, say) may still meaningfully degrade calibration without triggering an alert. The system is not self-healing; it depends on operator judgment for boundary cases.

---

## Example 4 — Coherence-Manufacturing on Noise (LLM-Assisted Brief)

### Scenario

A signal fires on a `mid`-liquidity macro market: `kalshi_cpi_q3_2026` ("Will US CPI exceed 3.0% in Q3 2026?"). The volume spike detector fires after a single position-closing trade pushes 1-hour volume 2.7× above baseline. Calibrated confidence: 0.41. The dashboard consumer has opted into LLM-assisted briefs.

### Detection

The signal is correctly emitted with the low confidence. Manipulation flags are empty (the trade was within size-vs-depth bounds). The signal proceeds through the deterministic context assembler and then through the optional LLM formatter.

### LLM Brief Output (After Forbidden-Token Check)

The LLM produces a brief that passes the forbidden-token check (it does not use the banned phrases) but still produces narrative implication:

> **Volume surge in Q3 CPI contract.** Hourly volume on `kalshi_cpi_q3_2026` rose to 2.7× baseline over the last hour. Movement is statistically significant. Investigation prompts: check recent CPI nowcasts; check Fed funds futures; check whether Treasury yields confirmed the expectation shift.

The brief is technically correct in every word. It does not assert causation. But a reader skimming the brief may infer that "expectation shift" is what happened. The signal, in fact, was triggered by a single trader closing a position.

### Symptom

The dashboard renders the brief. A human reader, primed by the framing, treats the volume surge as informative and pulls up CPI nowcasts. The investigation reveals nothing of note. The reader has spent ten minutes verifying nothing.

### Consumer Mitigation

| Layer                 | Mitigation                                                                                                                                             |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Calibration           | The `confidence: 0.41` is the primary defense. Consumers filtering on `confidence ≥ 0.7` would not see this brief.                                     |
| LLM provenance        | `interpretation_mode = "llm_assisted"` is on the brief. Consumers can filter to `deterministic` only if they want to avoid LLM framing entirely.       |
| Forbidden-token check | Catches the most flagrant causal phrasings. Does not catch all coherence-manufacturing patterns.                                                       |
| Documentation         | `../methodology/calibration-methodology.md` and `../foundations/non-goals.md` document the LLM formatter's limits. Consumers who read them are warned. |

### Residual Risk

The LLM formatter is fundamentally a coherence-manufacturing engine. The forbidden-token check raises the bar but does not remove the risk. The deterministic Markdown formatter is available as a safer alternative; consumers preferring deterministic output should configure their integration accordingly.

This is the strongest argument for the LLM formatter being secondary and opt-in. A consumer that opts in is taking responsibility for this residual risk.

---

## Common Lessons from Negative Paths

1. **Manipulation flags are not magic.** The detector is conservative; consumers must apply suppression policy and investigate flagged signals.
2. **Silence is not safety.** Augur covers a bounded scope; the absence of a signal means no qualifying market signal, not the absence of underlying events.
3. **Calibration is fragile.** Reliability curves degrade under regime change; the drift monitor depends on operator judgment.
4. **LLM briefs are not authoritative.** Even with forbidden-token checks, LLM output can mislead; the deterministic formatters are the safer default.
5. **The `confidence` field is the primary defense.** A consumer who ignores it sees more false positives than a consumer who filters on it.

These lessons are inherent to the design, not bugs to be fixed. Augur's architecture acknowledges them; consumers who work with the architecture rather than against it get more value with less harm.
