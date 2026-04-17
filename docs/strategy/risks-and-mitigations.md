# Risks and Mitigations

This is the comprehensive risk register for Augur. Risks are grouped by type and ranked within each group. Every risk has a named mitigation. Risks without mitigations are escalated to `../open-questions.md`.

## Technical Risks

### Calibration drift invalidates `confidence` silently

**Severity:** High.
**What happens:** A regime change (e.g., new participant mix on Polymarket, expansion of Kalshi categories, or a structural shift in how a market type trades) shifts the raw-score distribution that the reliability curves were built on. Calibrated `confidence` values become unreliable while still appearing valid to consumers.
**Mitigation:** PSI and KS drift monitors run nightly per `../methodology/calibration-methodology.md`. A `CalibrationStaleEvent` fires when PSI > 0.2 or KS p < 0.01. Operators decide whether to recalibrate or accept the alert. Phase 5 may add automated recalibration; Phase 1 is alert-only.

### Manipulation indistinguishable from informed flow

**Severity:** High.
**What happens:** A manipulator's order pattern matches the same statistical signatures as a single informed trader. The manipulation detector flags the pattern, but Augur cannot prove the intent. A consumer who suppresses on flag matches loses legitimate signals; a consumer who ignores flags is exposed to manipulation amplification.
**Mitigation:** Manipulation flags are descriptive, not prescriptive — Augur attaches them and lets consumers apply policy. Recommended per-consumer suppression defaults are in `../methodology/manipulation-taxonomy.md`. The flag list is conservative (catches only obvious patterns) to keep false-flag rates low.

### BOCPD boundary failures near 0 or 1

**Severity:** Medium.
**What happens:** Even with the Beta-Binomial observation model, prices that cling near 0.02 or 0.98 produce posterior distributions that the run-length update can mishandle. Spurious changepoint signals fire, or genuine changepoints are missed.
**Mitigation:** Resolution exclusion (six hours before `closes_at`) covers the most common boundary regime. For markets that trade near boundaries throughout their life (e.g., a contract on a near-certain outcome), the calibration layer's per-market FPR computation captures the reduced precision and adjusts confidence accordingly. The market is not removed from the watchlist; consumers see lower-confidence signals.

### Cold-start blackout after engine restart

**Severity:** Medium.
**What happens:** BOCPD requires approximately 500 observations to stabilize. After a restart, every detector enters a 4-hour blackout (at 30 s polling) during which no signals fire on a market.
**Mitigation:** Detector state is serialized via `state_dict()` and `load_state()`. The engine persists state nightly and reloads on startup. For unplanned restarts, the engine replays recent snapshots from DuckDB to warm detectors before resuming live processing. Cold-start blackout is documented; consumers should not expect signals in the first 30 minutes after a known restart.

### Storm-mode signal drops lose information

**Severity:** Medium.
**What happens:** During a signal storm (e.g., a Federal Reserve announcement coinciding with a geopolitical event), the dedup layer enters cluster-only output and the LIFO drop policy discards older signals from the bus queue. Specific per-market signals can be lost.
**Mitigation:** Storm-mode behavior is documented in `../architecture/deduplication-and-storms.md`. Dropped signals are persisted to the `signals` table for post-hoc review, even though they did not reach the bus. Backtests measure the storm-drop rate. Raising bus capacity is the operational lever; the design accepts the accuracy cost as a trade for stability.

## Operational Risks

### API rate-limit exhaustion

**Severity:** Medium.
**What happens:** A surge in market activity promotes many markets to `hot` polling, exceeding the per-platform rate limit. Polling fails, feature pipeline stalls, detectors miss signals.
**Mitigation:** Rate-limit budget is computed per `../architecture/adaptive-polling-spec.md`. The scheduler caps utilization at 70% of the published limit. If pressure exceeds 80%, the scheduler demotes lowest-priority `hot` markets to `warm`. Backoff is exponential with a 5-retry cap. A `RateLimitPressureEvent` alerts operators.

### DuckDB scaling cliff at ~80M snapshots

**Severity:** Medium.
**What happens:** As the snapshot table grows, write latency increases and backtest queries lock the file. Live ingest stalls.
**Mitigation:** Migration triggers are explicit in `../architecture/storage-and-scaling.md`. Snapshots older than 7 days are exported to a Parquet archive nightly, keeping the hot table small. Backtest queries run against the archive. Migration to TimescaleDB triggers when the hot table exceeds 80M rows, P95 backtest latency exceeds 30 seconds, or P99 ingest latency exceeds 500 ms.

### Single-process failure modes (Phase 1 MVP)

**Severity:** Medium.
**What happens:** The MVP runs as a single asyncio process on a single machine. Any unhandled exception, OS-level crash, or hardware failure halts ingestion and detection.
**Mitigation:** A process supervisor (systemd, launchd, Docker restart policy) restarts the engine on crash. State serialization minimizes the cold-start cost. Consumers tolerate up to 30 minutes of feed gap. Phase 5 multi-process decomposition removes the single point of failure but is deferred until growth thresholds fire.

### Annotator disagreement on the labeled corpus

**Severity:** Low.
**What happens:** Human annotators disagree on event existence, timestamp, market association, or category. If agreement falls below the targets in `../methodology/labeling-protocol.md`, calibration becomes inconsistent across annotators.
**Mitigation:** The labeling protocol enforces double-labeling for the first 90 days and a third-annotator escalation for disagreements above the targets. Agreement metrics are computed and reportable. After 90 days of meeting targets, single labeling is permitted with quarterly spot audits.

## Business and Legal Risks

### Polymarket offshore status changes

**Severity:** High.
**What happens:** Polymarket operates offshore relative to US regulators. A regulatory action that restricts US-resident access, requires US licensing, or shutters the platform entirely removes one of two primary data sources. The watchlist loses approximately 60% of markets.
**Mitigation:** Multi-platform design from day one. The poller interface and normalizer abstract platform-specific logic; adding a third platform (Manifold, Predictit successor, EU-regulated platform when available) requires only an adapter. Historical Polymarket data in the Parquet archive supports continued backtesting of detectors and methodology. Calibration on remaining platforms (Kalshi, future additions) continues with reduced sample size; reliability curves are recomputed on the new mix.

### Kalshi tightens commercial-use ToS

**Severity:** Medium.
**What happens:** Kalshi's terms of service evolve to require a commercial license for automated data collection at Augur's scale, or restrict redistribution of derived signals.
**Mitigation:** Augur monitors ToS changes for both platforms. The system does not redistribute raw market data — it produces derived signals that are arguably outside the scope of typical ToS restrictions. If commercial licensing is required, the operator negotiates with Kalshi or restricts the watchlist to publicly accessible markets. The architecture supports per-market opt-out via the watchlist configuration.

### Regulatory action against prediction-market category broadly

**Severity:** Medium.
**What happens:** A US or UK regulator decides prediction markets constitute illegal gambling or unauthorized derivatives, restricting the entire category. Both data sources potentially affected.
**Mitigation:** Augur is a news intelligence product, not a trading product. The system does not advise trades or take positions. Regulatory exposure is therefore limited to the data-collection question, not the financial-advice question. If both platforms become inaccessible, the system enters a maintenance mode operating on archived data; consumers receive degraded coverage. There is no full mitigation against the loss of the data category itself.

### Consumer over-trust in `confidence` field

**Severity:** Medium.
**What happens:** A consumer treats `confidence` as a probability of the underlying event occurring rather than as the empirical precision of the signal. Decisions made on this misreading lead to losses or reputational damage attributed to Augur.
**Mitigation:** `../methodology/calibration-methodology.md` explicitly states what `confidence` means and what it does not. The glossary in `../foundations/glossary.md` reinforces the definition. Consumer integration documentation (a future deliverable) restates the meaning. Augur cannot prevent consumer misinterpretation but documents the semantics clearly.

### LLM-rendered briefs misleading downstream readers

**Severity:** Medium.
**What happens:** A consumer that opts into LLM-assisted briefs reads a coherent-sounding narrative and treats it as authoritative. The narrative passes the forbidden-token check (it does not use banned phrases) but still implies causality the data does not support.
**Mitigation:** LLM formatter is gated, opt-in, and routed to human channels only by default. Provenance stamping makes every LLM brief identifiable by `interpretation_mode = llm_assisted`. The forbidden-token check catches the most common causal-narrative patterns; the residual risk is real and acknowledged. Consumers using LLM briefs should treat them as draft text for human review, not as authoritative claims.

## Epistemic Risks

### False-positive narrative laundering

**Severity:** High.
**What happens:** A statistically real but spurious detector signal is interpreted by a downstream LLM consumer (or by a human reader of an LLM brief) as a meaningful event. The narrative gives the false signal credibility it does not deserve. The consumer acts on it and the action turns out to be wasted or wrong.
**Mitigation:** Calibrated `confidence` is the primary defense — consumers who filter on high confidence see fewer false positives. The LLM formatter's restricted vocabulary prevents the most flagrant causal claims. The deterministic Markdown formatter is available as a less-evocative alternative. The fundamental mitigation is consumer literacy: documentation in `../examples/negative-paths.md` shows what false positives look like and how to recognize them.

### Calibration trained on biased event sources

**Severity:** Medium.
**What happens:** The labeled corpus draws from a finite set of qualifying English-language financial sources. Calibration is therefore valid for events well-covered by those sources; events outside that coverage have weaker calibration. Consumers using Augur in non-US, non-finance contexts may see misleading confidence values.
**Mitigation:** The labeling protocol's source bias is documented in `../methodology/labeling-protocol.md`. Calibration is conditional on the protocol; consumers in different domains should compute their own per-consumer reliability curves on their own labels. Adding non-English sources is an open question in `../open-questions.md`.

### Manipulation amplification reputation

**Severity:** Medium.
**What happens:** A manipulator deliberately moves a market with the intent of triggering an Augur signal that gets amplified by news desks, then unwinds the position into the resulting attention. If this happens publicly, Augur's reputation as a reliable source degrades.
**Mitigation:** The manipulation detector flags the most common manipulation patterns. News desk consumers' recommended suppression defaults exclude signals with `single_counterparty_concentration` or `cancel_replace_burst` flags. Augur publishes the manipulation taxonomy openly so consumers understand the limits. The risk is asymmetric — a single visible amplification incident does more reputational damage than many quiet correct signals; consumer suppression policies should err toward conservative.

## Mitigations Table

| Risk                              | Severity | Mitigation Mechanism                                    | Mitigation Doc                                |
| --------------------------------- | -------- | ------------------------------------------------------- | --------------------------------------------- |
| Calibration drift                 | High     | PSI/KS monitors, alert + manual recalibration           | `../methodology/calibration-methodology.md`   |
| Manipulation indistinguishability | High     | Flag attached, suppression policy is consumer-side      | `../methodology/manipulation-taxonomy.md`     |
| BOCPD boundary failures           | Medium   | Pre-resolution exclusion, per-market calibration        | `../methodology/calibration-methodology.md`   |
| Cold-start blackout               | Medium   | State serialization, snapshot replay                    | `../architecture/system-design.md`            |
| Storm-mode signal drops           | Medium   | LIFO drop, signals persisted, documented cost           | `../architecture/deduplication-and-storms.md` |
| API rate exhaustion               | Medium   | 70% utilization cap, demotion under pressure            | `../architecture/adaptive-polling-spec.md`    |
| DuckDB scaling cliff              | Medium   | Explicit migration triggers, archive partitioning       | `../architecture/storage-and-scaling.md`      |
| Single-process failure            | Medium   | Process supervisor, state serialization                 | `../architecture/system-design.md`            |
| Annotator disagreement            | Low      | Double labeling, third-annotator escalation             | `../methodology/labeling-protocol.md`         |
| Polymarket offshore status        | High     | Multi-platform abstraction, archive preserves backtests | `../architecture/system-design.md`            |
| Kalshi ToS tightening             | Medium   | Per-market opt-out, platform negotiation                | `../architecture/system-design.md`            |
| Regulatory action on category     | Medium   | News intelligence framing, no trading exposure          | `../foundations/non-goals.md`                 |
| Confidence over-trust             | Medium   | Documentation of semantics                              | `../methodology/calibration-methodology.md`   |
| LLM brief misleading              | Medium   | Gated, opt-in, restricted vocabulary, provenance        | `../methodology/calibration-methodology.md`   |
| False-positive laundering         | High     | Calibrated confidence, restricted vocabulary, examples  | `../examples/negative-paths.md`               |
| Calibration source bias           | Medium   | Documented limits, consumer-side recalibration          | `../methodology/labeling-protocol.md`         |
| Manipulation amplification        | Medium   | Flag attachment, conservative consumer defaults         | `../methodology/manipulation-taxonomy.md`     |
