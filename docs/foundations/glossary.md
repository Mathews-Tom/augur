# Glossary

Authoritative definitions for terms used across Augur's documentation. If a term appears in any other document, its definition lives here. Entries are alphabetical.

## Brief

A rendered output produced by a formatter from a `SignalContext`. May be JSON, Markdown, a webhook payload, a WebSocket frame, or LLM-rendered prose. Briefs are derivative artifacts; the canonical contract is the underlying `MarketSignal` and `SignalContext`. See `../contracts/schema-and-versioning.md`.

## Calibrated Confidence

The `confidence` field on a `MarketSignal`. A value in [0, 1] computed by mapping a detector's raw score through an empirically derived reliability curve. Calibrated confidence answers "what fraction of signals at this score are true positives in held-out labeled data," not "how strongly does the model fit the observation." Raw detector scores are stored separately in `raw_features` for diagnostic use. Defined operationally in `../methodology/calibration-methodology.md`.

## Consumer

A downstream system that subscribes to Augur's signal feed. Consumers are typed by the closed `ConsumerType` enum in `../contracts/consumer-registry.md`. Examples include macro research agents, geopolitical research agents, financial news desks, and human-facing dashboards.

## Cross-Market Divergence

A signal type fired when two markets that the curated taxonomy identifies as related (positively, inversely, or by causal linkage) move inconsistently with the historical correlation between them. Detected using Spearman rank correlation, Fisher-z transformation, and Benjamini-Hochberg correction across all candidate pairs.

## FDR

False Discovery Rate. The expected fraction of detected signals that are false positives. Augur controls FDR using the Benjamini-Hochberg procedure across batches of candidate signals within a polling cycle. Target FDR is configurable; default is 0.05.

## Hysteresis Band

A guard band around a threshold that prevents rapid flapping when a measurement sits near the threshold value. The adaptive polling state machine uses ±10% bands on volume thresholds to prevent polling-rate jitter that would contaminate rolling-window features. See `../architecture/adaptive-polling-spec.md`.

## Interpretation Mode

A field on `SignalContext` and on rendered briefs that records how the brief was produced. Values are members of the `InterpretationMode` enum: `DETERMINISTIC` (template-rendered from facts only) or `LLM_ASSISTED` (rendered by a gated LLM formatter, restricted vocabulary). Consumers can route or filter on this field.

## Investigation Prompt

A pre-curated text directive returned to the consumer alongside a signal, instructing them where to look for context. Investigation prompts are keyed by `(signal_type, market_category)` and stored in `data/investigation_prompts.toml`. They are never generated at runtime; the library is frozen after load and runtime additions throw.

## Lead Time

The interval between when a `MarketSignal` was detected and when the corresponding `NewsworthyEvent` was first published by a qualifying source. Computed as `event.ground_truth_timestamp - signal.detected_at`. A signal is a true positive if its lead time is in the range (0, 24h]. Defined in `../methodology/labeling-protocol.md`.

## Liquidity Tier

A coarse banding of markets by daily USD volume, used to gate detector behavior and weight calibration. Bands:

| Tier   | Daily USD Volume    |
| ------ | ------------------- |
| `high` | ≥ $250,000          |
| `mid`  | $50,000 to $250,000 |
| `low`  | $10,000 to $50,000  |

Markets below $10,000 daily volume are excluded from the tracked watchlist. Tier assignments are recomputed daily from a 7-day rolling window.

## Manipulation Flag

A member of the `ManipulationFlag` enum attached to a `MarketSignal` when one or more manipulation signatures match the surrounding market state. Flags are descriptive, not prescriptive — Augur does not suppress flagged signals; consumers decide their own suppression policy. The signature catalog is in `../methodology/manipulation-taxonomy.md`.

## MarketSignal

The canonical structured event emitted by the signal extraction layer. Carries the market identifier, signal type, magnitude, direction, calibrated confidence, manipulation flags, and provenance metadata. The schema is defined in `../contracts/schema-and-versioning.md` and is the binding contract between the extraction and context-assembly layers.

## Newsworthy Event

A real-world event that an editorially independent source has reported. Operationally defined as an event documented by at least two of the qualifying source set (Reuters, Bloomberg, Associated Press, Financial Times) within a 24-hour window. The earliest qualifying publication timestamp is the event's `ground_truth_timestamp`. The full operational definition, source hierarchy, and labeling rules are in `../methodology/labeling-protocol.md`.

## Pre-Resolution Window

The interval before a market's `closes_at` timestamp during which detectors are silenced because price movement is structurally driven by the contract approaching its terminal value rather than by new information. The window is six hours and is enforced uniformly across all detectors. See `../architecture/system-design.md`.

## Regime Shift

A signal type fired when a market's rolling volatility transitions between low (consolidation) and high (active trading) regimes. Detected using two-sided CUSUM with adaptive cooldown and a six-hour minimum dormancy period.

## Reliability Curve

A monotone calibration function mapping a detector's raw score (e.g., a BOCPD posterior probability) to an empirically calibrated confidence. Built from labeled signal/event data using decile binning of (mean raw score, observed precision) pairs. Defined in `../methodology/calibration-methodology.md`.

## Resolution Criteria

The verbatim text from the platform describing under what conditions a contract resolves to YES or NO. Carried unchanged through the system; the context assembler injects this text into the `SignalContext` without modification.

## Resolution Source

The verbatim authoritative source named by the platform for resolving the contract (e.g., "Federal Reserve FOMC statement"). Carried unchanged through the system.

## Run-Length Distribution

The internal state of the Bayesian Online Changepoint Detection (BOCPD) detector. A discrete probability distribution over the number of observations since the last detected changepoint. Capped at a configurable maximum length (default 1000) to bound memory.

## Schema Version

A semver string on every contract type indicating which version of the schema the message conforms to. Current is `1.0.0`. The versioning policy is in `../contracts/schema-and-versioning.md`. Breaking changes require a major-version bump and consumer migration notes.

## Signal

Shorthand for `MarketSignal`. See above.

## SignalContext

The deterministic output of the context assembler. Wraps a `MarketSignal` with verbatim market metadata, related-market state, and curated investigation prompts. Contains no synthesized text. The schema is in `../contracts/schema-and-versioning.md`.
