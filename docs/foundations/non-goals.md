# Non-Goals

This document is the authoritative boundary statement. Anything listed here is explicitly outside Augur's design space. Reading this before forming expectations about Augur's coverage is mandatory.

## Not a Trading System

Augur does not place orders, does not maintain positions, does not advise trades, and does not compute portfolio metrics. The output is structured intelligence, not actionable alpha. Consumers of Augur's feed who choose to trade on its output do so at their own risk and outside Augur's design intent.

## Not a Prediction Engine

Augur does not predict outcomes. It detects when the market's aggregate probability assignment is changing in a statistically significant way. A `MarketSignal` describes a movement in the market's belief, not Augur's belief about the underlying event. Augur has no view on whether the Fed will cut rates; it has a view on whether the Kalshi contract on that question is moving anomalously.

## Not a Sentiment Tool

Augur does not scan social media, news text, or community discussion for sentiment. It operates on quantitative market microstructure (price, volume, book depth, trade flow) and on verbatim platform metadata (question text, resolution criteria, resolution source). The optional LLM formatter operates on a `SignalContext` envelope, not on free text.

## Not a Black-Swan Early-Warning System

Augur does not detect emerging news for which no market exists. The data source is prediction markets, and the data source's coverage determines Augur's coverage. Genuinely novel events — sudden geopolitical escalations, unanticipated banking failures, surprise regulatory actions, novel scientific results — do not have pre-existing markets with sufficient depth. Such events appear in Augur's feed only after a market has been created and reached the liquidity floor, which is typically after the news has broken through traditional channels. Treat the absence of an Augur signal during a black-swan event as the expected behavior, not a failure.

## Not a Causal Inference Engine

Augur does not generate hypotheses about why a market moved. It reports the magnitude and direction of the move, the resolution criteria, the state of related markets, and a list of curated investigation prompts. Causal interpretation is the consumer's responsibility. The optional LLM formatter is constrained by a forbidden-token vocabulary that bans the standard causal-narrative phrases enumerated in `../methodology/calibration-methodology.md`. The constraint exists because a coherent-sounding causal narrative manufactured from a price delta is more harmful than no narrative at all — it short-circuits the consumer's investigation.

## Not a Topic Coverage Promise

Augur does not promise coverage of any specific topic. The topic distribution of Polymarket and Kalshi is heavily skewed toward sports, US politics, crypto, and US macroeconomics. Topics outside these clusters typically lack pre-existing markets or have markets with insufficient depth to generate clean signals. Topics inside these clusters are covered when individual markets meet the high or mid liquidity tier defined in `./glossary.md`. Coverage is a function of market existence and depth, not a function of topic priority.

## Markets Out of Scope

Augur does not produce signals on:

- Markets with daily volume below the low-tier USD floor defined in `./glossary.md`. Thin markets generate noise that no detector calibration can convert into reliable signal.
- Markets within six hours of resolution. Pre-resolution price movement is structurally driven by the contract approaching its terminal value and is excluded from detection.
- Markets without machine-readable resolution criteria. The context assembler requires verbatim resolution text; markets without it cannot be enriched and are skipped.
- Markets on platforms other than Polymarket and Kalshi at this stage. Adding a platform requires a normalizer adapter and a manipulation-signature review.

## Time Horizons Out of Scope

Augur does not produce signals on intraday price wiggles below the 5-minute window. The minimum feature window is 5 minutes; signals require movement that persists through the rolling window. High-frequency micro-movements are explicitly filtered as noise.

Augur also does not retain signal history beyond the storage retention defined in `../architecture/storage-and-scaling.md`. Long-horizon trend analysis is the consumer's responsibility.

## Categories Augur Will Not Cover Even If Markets Exist

Some categories appear in prediction markets but are explicitly excluded from Augur's curated taxonomy:

- Individual celebrity outcomes (divorces, scandals, awards) — high noise, low public-interest value, manipulation-prone.
- Sports event outcomes — high volume on these platforms but outside Augur's intelligence-product framing. A separate consumer can build on the raw signal extraction layer if useful.
- Personal speculation contracts (will person X tweet, will event Y be cancelled) — coverage decision deferred; treated as out of scope for Phase 1.

The exclusion list is part of the curated taxonomy in the configuration; it is not a hard codebase constraint and can be revised through the schema governance process.
