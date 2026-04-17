# Manipulation Taxonomy

This document defines the manipulation signatures Augur detects, the algorithmic implementation of each signature, and the documented historical episodes that motivate them. Manipulation detection runs on every signal; the result is attached as `manipulation_flags` to the `MarketSignal`.

## Why Detection Is Not Suppression

Augur flags manipulation; it does not suppress flagged signals. Suppression is a policy decision that depends on the consumer's risk tolerance and use case. A research agent investigating market manipulation explicitly wants to see flagged signals. A news desk publishing summaries explicitly wants to suppress them. The same signal goes to both consumers with the same flag set; each consumer applies its own policy.

This separation is non-negotiable. A detector that suppresses on flag matches has made a policy decision the consumer should make. Augur reports facts and lets policy live where it belongs.

A second reason: Augur cannot prove manipulation. A signature match is necessary evidence, not sufficient evidence. A whale executing a large trade for legitimate reasons (covering risk, rebalancing) produces the same signature as a whale executing for manipulation. Suppressing on signature match would lose legitimate signals; the consumer is in a better position to evaluate context.

## Signature Catalog

### `single_counterparty_concentration`

**Definition.** One counterparty's volume share within a trade window exceeds a Herfindahl-index threshold.

**Computation.** For each trade in the window preceding a signal, compute the per-counterparty volume share. The Herfindahl index is the sum of squared shares. Default threshold: 0.4 (equivalent to roughly 60% of volume from one counterparty in a relatively concentrated regime).

**Why it matters.** Information arrival typically produces buying pressure across many participants reacting to the same news. Concentration on a single counterparty is the signature of either a single informed trader or a manipulator; the two are distinguishable only with additional context (book impact, trade size relative to depth, surrounding cancel-replace activity).

**Limitation.** Polymarket counterparty identification is wallet-derived; sophisticated manipulators use multiple wallets. The Herfindahl threshold is a coarse first-pass filter, not a definitive test.

### `size_vs_depth_outlier`

**Definition.** A single trade consumed more than the configured fraction of resting depth at the time of the trade.

**Computation.** For each trade in the window, compute `trade_size / book_depth_immediately_before_trade`. A trade exceeding the configured ratio (default 0.4) flags this signature.

**Why it matters.** A trade that consumes 40%+ of the resting book is unusual under normal information arrival, where informed traders typically split orders to minimize impact. Sweeping the book is the signature of a participant either prioritizing speed over impact (rare for legitimate flow on these markets) or deliberately moving the price.

**Limitation.** Markets at the low end of the high-tier liquidity range can have shallow books where 40% consumption is achievable on modest absolute trade sizes. Tier-conditional ratios are a future refinement.

### `cancel_replace_burst`

**Definition.** Cancel-replace event count within a short burst window exceeds a threshold.

**Computation.** Count distinct cancel-replace events on the order book within a configurable window (default 60 seconds). A count exceeding the threshold (default 20) flags this signature.

**Why it matters.** Rapid cancel-replace activity is the signature of book-painting or layering strategies, where a participant places orders they intend to cancel before execution to create a misleading depth picture. This is a known manipulation pattern in equity markets and has been observed on prediction markets at lower frequencies.

**Limitation.** Polymarket and Kalshi do not expose a clean cancel-replace event stream; this signature is computed from book-state diffs and undercounts true cancel-replace activity. The signature is conservative — it flags only obvious bursts.

### `thin_book_during_move`

**Definition.** Median book depth across the move window was below a minimum-depth USD floor.

**Computation.** For each snapshot in the window during which the signal-generating move occurred, compute total resting depth (top 5 levels). The median across the window is compared to the minimum-depth floor (configurable per platform; default $5,000 USD). A median below the floor flags this signature.

**Why it matters.** Price moves on thin books are mechanically easier to manufacture. A signal generated on a market whose median depth during the move was $3,000 reflects substantially less trader consensus than the same nominal price move on a market with $50,000 median depth.

**Limitation.** Depth measurement is platform-dependent; Kalshi's depth representation differs from Polymarket's. Tier-conditional floors and platform-conditional adjustments are tracked in the configuration.

### `pre_resolution_window`

**Definition.** The signal occurred within the six-hour window before the market's `closes_at` timestamp.

**Computation.** Compute `closes_at - signal.detected_at`. If the result is less than six hours, flag this signature.

**Why it matters.** Within the pre-resolution window, price movement is structurally driven by the contract approaching its terminal value (0 or 1) as the resolution event becomes near-certain. This is not manipulation per se, but signals fired in this window have low information value and frequently coincide with actual manipulation attempts (last-mile pumps, settlement-driven trades). The flag groups these together as "low-confidence settlement-window activity."

**Note.** The original Phase 1 detector spec excludes signals in this window from firing at all. This flag exists for completeness in the contract; in practice, signals carrying this flag should not appear in production output if the detector layer is correctly implemented.

## Detection Implementation

The manipulation detector is a stateless evaluator. It receives a `MarketSignal` plus the recent trades, book events, and snapshots for the surrounding window, runs each signature function, and returns a list of matched flags. The signature functions are pure functions of their inputs and have no internal state.

Algorithmic summary:

```python
def evaluate(signal, recent_trades, recent_book_events, recent_snapshots):
    flags = []
    if single_counterparty_concentration(recent_trades) > herfindahl_threshold:
        flags.append(SINGLE_COUNTERPARTY_CONCENTRATION)
    if any(size_vs_depth_outlier(t, depth_before(t)) for t in recent_trades):
        flags.append(SIZE_VS_DEPTH_OUTLIER)
    if cancel_replace_burst(recent_book_events) >= burst_threshold:
        flags.append(CANCEL_REPLACE_BURST)
    if median_depth(recent_snapshots) < min_depth:
        flags.append(THIN_BOOK_DURING_MOVE)
    if (signal.market.closes_at - signal.detected_at) < timedelta(hours=6):
        flags.append(PRE_RESOLUTION_WINDOW)
    return flags
```

The evaluator runs once per signal and is bypass-resistant — there is no codepath in the engine that emits a signal without first running the evaluator.

## Known Historical Episodes

The following episodes are documented in public reporting and inform the signature design. They are listed for calibration reference; Augur does not republish or characterize the episodes.

| Episode                                                         | Year | Platform   | Signature(s) Most Relevant                                   |
| --------------------------------------------------------------- | ---- | ---------- | ------------------------------------------------------------ |
| Large coordinated trades on US presidential election contracts  | 2024 | Polymarket | `single_counterparty_concentration`, `size_vs_depth_outlier` |
| Mid-curve squeeze on a thinly-traded outcome contract           | 2024 | Polymarket | `thin_book_during_move`, `size_vs_depth_outlier`             |
| Settlement-window pump on a sports outcome contract             | 2024 | Polymarket | `pre_resolution_window`, `size_vs_depth_outlier`             |
| Layering pattern on an economic-indicator contract              | 2025 | Polymarket | `cancel_replace_burst`                                       |
| Wash-trading pattern on a low-volume crypto-regulatory contract | 2025 | Polymarket | `single_counterparty_concentration`, `thin_book_during_move` |

The Phase 1 implementation calibrates each signature against the corresponding episode set as part of the test harness. Adding new signatures requires at least one documented historical episode that motivates the signature.

## Consumer Suppression Policies

Each consumer applies its own policy. Recommended defaults:

| Consumer                      | Suppression Default                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------ |
| `macro_research_agent`        | Pass through all flags; no suppression.                                              |
| `geopolitical_research_agent` | Pass through all flags; no suppression.                                              |
| `crypto_research_agent`       | Pass through all flags; explicit interest in manipulation patterns.                  |
| `financial_news_desk`         | Suppress signals with `single_counterparty_concentration` or `cancel_replace_burst`. |
| `regulatory_news_desk`        | Suppress signals with `pre_resolution_window`.                                       |
| `dashboard`                   | Pass through all flags; visually badge flagged signals.                              |

These defaults are recommendations, not enforcement. The closed `ConsumerType` enum in `../contracts/consumer-registry.md` does not encode suppression policy; consumers configure suppression at their boundary.

## Limitations

Augur's manipulation detection has the following hard limits, which consumers must understand:

1. **Signature match is not proof.** A signature match means a manipulation pattern is present; it does not mean manipulation occurred. Distinguishing legitimate large-trader activity from manipulation requires investigation outside Augur's scope.
2. **False negatives are common.** Sophisticated manipulators can avoid all signatures by spreading volume across wallets, splitting trades, and using smaller relative sizes. The detector catches obvious patterns, not careful ones.
3. **Platform data limits the detection surface.** Polymarket and Kalshi do not expose all the data needed for high-fidelity manipulation detection (e.g., wallet linkage analysis, order intent metadata). Augur uses what is available.
4. **The detector cannot infer motivation.** A trader covering hedge exposure, rebalancing a portfolio, or taking a directional view all produce trade footprints that may match signatures. Augur reports the footprint; consumers infer motivation if they have additional context.
