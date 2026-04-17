# Pitch

## Problem

For a small set of prediction markets — those with deep liquidity tied to anticipated events such as Federal Reserve decisions, scheduled US elections, regulatory milestones, and major crypto-asset filings — the price tape carries information that systematic monitoring can convert into useful intelligence. The information is locked in the derivative of the price (velocity, volume relative to baseline, cross-market consistency) rather than the price level itself, and across hundreds of markets no one is extracting it continuously, calibrating it against ground truth, and packaging it as machine-readable events. Analysts watch dashboards manually or not at all. Downstream agents that could route on a structured signal do not get one.

## Insight

The signal worth extracting is not the absolute price. It is a calibrated change in the price relative to that market's history, weighted by the volume behind the change, and contextualized against related markets in a curated taxonomy. The detector layer is a classical signal processing problem with well-understood algorithms applied to bounded-domain data. The interpretation layer, in contrast, is the dangerous part: an LLM asked to explain why a market moved will reliably produce a coherent-sounding narrative regardless of whether a real cause is identifiable. Augur draws the line in the right place — calibration and detection are mandatory, causal interpretation is the consumer's responsibility.

## What We'd Build

A two-layer system. The signal extraction layer ingests Polymarket and Kalshi market data via polling, computes rolling features, runs five detectors (Beta-Binomial BOCPD, FDR-controlled volume spike, depth-gated book imbalance, Spearman + Fisher-z + Benjamini-Hochberg cross-market divergence, two-sided CUSUM regime shift), and attaches manipulation flags to every signal. Confidence on each signal is empirically calibrated against a labeled corpus of newsworthy events, not derived from raw detector posteriors.

The context assembly layer retrieves the market question, resolution criteria, and resolution source verbatim, looks up related markets from a curated taxonomy with current state, and lists pre-curated investigation prompts keyed to the signal type and market category. The output is a `SignalContext` envelope: structured, deterministic, fact-only.

A secondary, opt-in LLM formatter can render a `SignalContext` into prose for human-facing channels. It is gated by `interpretation_mode = LLM_ASSISTED`, restricted by a forbidden-token vocabulary, and never substitutes for the canonical structured output. It does not run by default and never appears on the agent JSON feed unless a consumer explicitly opts in.

## Why Not a Trading System

Augur does not trade, does not advise trades, and does not predict outcomes. It detects when the market's collective prediction is changing in statistically significant ways and reports the facts needed for a downstream consumer to investigate. The output is intelligence, not alpha. The consumer is a research agent or news desk, not a portfolio manager. This separation simplifies regulatory exposure, broadens applicability beyond capital markets, and lets the system optimize for signal quality and calibration rather than execution latency.

## Why Now

Polymarket processed several billion dollars of volume in 2024, and Kalshi continues to expand under CFTC regulation. For the narrow band of markets that are deeply liquid and tied to anticipated events, the prices are informative enough that a well-calibrated detector produces useful signals. Bounded-domain statistical methods (Beta-Binomial BOCPD, Spearman correlation with FDR control) are well understood and implementable in a few hundred lines of Python with numpy and scipy. Local LLMs are now capable enough to render the optional secondary brief without cloud API costs, though the architecture treats LLM interpretation as a gated formatter rather than a source of truth.

## What a Signal Looks Like

A deterministic example, with no synthesized causal language:

```json
{
  "signal": {
    "signal_id": "01HX4N0QRZ8K7M3F0E9G6V5BWA",
    "market_id": "kalshi_fed_rate_june_2026",
    "platform": "kalshi",
    "signal_type": "price_velocity",
    "magnitude": 0.78,
    "direction": 1,
    "confidence": 0.72,
    "fdr_adjusted": true,
    "detected_at": "2026-04-14T14:32:00Z",
    "window_seconds": 7200,
    "liquidity_tier": "high",
    "manipulation_flags": [],
    "related_market_ids": ["kalshi_fed_holds_2026", "polymarket_inflation_q2"],
    "raw_features": {
      "posterior_p_change": 0.92,
      "calibration_provenance": "v1.3"
    },
    "schema_version": "1.0.0"
  },
  "market_question": "Will the Fed cut rates at the June 2026 FOMC meeting?",
  "resolution_criteria": "Resolves YES if the FOMC reduces the target federal funds rate at the June 2026 meeting.",
  "resolution_source": "Federal Reserve FOMC statement",
  "closes_at": "2026-06-15T18:00:00Z",
  "related_markets": [
    {
      "market_id": "kalshi_fed_holds_2026",
      "current_price": 0.22,
      "delta_24h": -0.08,
      "relationship_type": "inverse"
    },
    {
      "market_id": "polymarket_inflation_q2",
      "current_price": 0.34,
      "delta_24h": 0.01,
      "relationship_type": "complex"
    }
  ],
  "investigation_prompts": [
    "Check FOMC calendar for upcoming meetings and statements",
    "Pull Federal Reserve governor speeches in the last 24 hours",
    "Review most recent CPI, PCE, and employment releases",
    "Check Fed funds futures curve for confirming move in adjacent tenors"
  ],
  "interpretation_mode": "deterministic",
  "schema_version": "1.0.0"
}
```

Note what is not present: any sentence claiming Augur knows why the market moved.

## Scope Bounds

Augur covers approximately 100 to 150 high-liquidity, anticipated-event markets across Polymarket and Kalshi. The data source determines the scope. Markets without pre-existing depth do not produce extractable signals, and most newsworthy events fall into that category. The non-goals list in `./non-goals.md` is authoritative on what is out of scope.

## Where the Moat Actually Builds

The algorithms are textbook. The APIs are public. The defensibility argument that survives contact with reality is the labeled signal-to-event corpus and the calibration knowledge derived from it — neither can be bootstrapped retroactively. The full thesis is in `../strategy/moat-thesis.md`.

## What We're Looking For

Open questions about positioning, monetization, platform expansion, and the path from classical detectors to learned ones are tracked in `../open-questions.md` with current best answers.
