# Positive-Path Examples

Concrete, worked examples of Augur producing genuine value. Each example shows the input signal, the deterministic context envelope, and the consumer's verification path. No example contains synthesized causal language — Augur reports facts; consumers do interpretation.

Every JSON payload below validates against `../contracts/schema-and-versioning.md`.

---

## Example 1 — FOMC Pre-Meeting Drift on a High-Liquidity Macro Market

### Scenario

The Kalshi contract `kalshi_fed_rate_june_2026` ("Will the Fed cut rates at the June 2026 FOMC meeting?") trades at 0.42 on Tuesday morning UTC, two days before the FOMC announcement. Over the next 36 hours, the price drifts from 0.42 to 0.58 on volume averaging 2.4× the 7-day baseline. The market is in the `high` liquidity tier ($800K daily volume).

### Detection

The Beta-Binomial BOCPD detector fires on the cumulative drift. The volume spike detector also fires. Both pass the BH-FDR threshold for the polling cycle. The manipulation detector evaluates the signatures and finds no matches. Calibrated `confidence` is 0.74 from the high-tier reliability curve for the price-velocity detector.

### `MarketSignal`

```json
{
  "signal_id": "01HX4N0QRZ8K7M3F0E9G6V5BWA",
  "market_id": "kalshi_fed_rate_june_2026",
  "platform": "kalshi",
  "signal_type": "price_velocity",
  "magnitude": 0.78,
  "direction": 1,
  "confidence": 0.74,
  "fdr_adjusted": true,
  "detected_at": "2026-04-14T14:32:00Z",
  "window_seconds": 129600,
  "liquidity_tier": "high",
  "manipulation_flags": [],
  "related_market_ids": [
    "kalshi_fed_holds_2026",
    "polymarket_inflation_q2",
    "kalshi_unemployment_q3"
  ],
  "raw_features": {
    "posterior_p_change": 0.91,
    "drift_pct": 0.16,
    "volume_ratio_24h": 2.4,
    "calibration_provenance": "price_velocity_bocpd_beta_v1@curve_v1.3"
  },
  "schema_version": "1.0.0"
}
```

### `SignalContext`

```json
{
  "signal": { "...as above..." },
  "market_question": "Will the Fed cut rates at the June 2026 FOMC meeting?",
  "resolution_criteria": "Resolves YES if the FOMC reduces the target federal funds rate at the June 2026 meeting.",
  "resolution_source": "Federal Reserve FOMC statement",
  "closes_at": "2026-06-15T18:00:00Z",
  "related_markets": [
    {"market_id": "kalshi_fed_holds_2026", "question": "Will the Fed hold rates through 2026?", "current_price": 0.22, "delta_24h": -0.08, "volume_24h": 312000, "relationship_type": "inverse", "relationship_strength": 0.9},
    {"market_id": "polymarket_inflation_q2", "question": "Will US CPI exceed 3% in Q2 2026?", "current_price": 0.34, "delta_24h": 0.01, "volume_24h": 145000, "relationship_type": "complex", "relationship_strength": 0.6},
    {"market_id": "kalshi_unemployment_q3", "question": "Will US unemployment exceed 4.5% in June 2026?", "current_price": 0.28, "delta_24h": 0.02, "volume_24h": 98000, "relationship_type": "positive", "relationship_strength": 0.5}
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

### Consumer Verification Path

A `macro_research_agent` receiving this brief follows the investigation prompts:

1. Pulls the FOMC calendar and confirms the June meeting is in 8 weeks.
2. Pulls speeches from the last 24 hours and finds two regional Fed presidents have made dovish remarks.
3. Pulls the most recent PCE release and observes a 10 bps undershoot vs consensus.
4. Checks the Fed funds futures curve and observes the 6-month tenor has moved 8 bps.

The agent now has independent corroboration. The Augur signal accelerated the agent's prioritization; the agent did the verification. Augur did not assert what was driving the move; the verification provides the answer.

### Why This Is a Positive Path

The signal is on a high-liquidity market in Augur's covered scope. The calibrated confidence (0.74) accurately reflects the empirical precision of similar signals. No manipulation flags. The consumer has a structured set of investigation steps and uses them. Augur's value is the time saved between the market move and the analyst's awareness.

---

## Example 2 — Cross-Market Divergence Flagging an Arbitrage Failure

### Scenario

Two Polymarket contracts on a geopolitical situation:

- `polymarket_invasion_xy` ("Will Country X invade Country Y before July 2026?") trading at 0.15
- `polymarket_unsc_session_xy` ("Will the UN Security Council hold an emergency session on Country X before July 2026?") trading at 0.65

Historical Spearman correlation between these markets: 0.71. Over a 4-hour window, the invasion market drops to 0.08 while the UNSC session market rises to 0.78. The Fisher-z distance from historical correlation crosses the BH-FDR threshold.

### Detection

The cross-market divergence detector fires. The contracts are in the `mid` liquidity tier ($85K daily on the invasion market, $72K on the UNSC market). Manipulation detector finds no matches. Calibrated confidence: 0.66 from the mid-tier divergence reliability curve.

### `MarketSignal`

```json
{
  "signal_id": "01HX4QQRZP4MFKNRQYJ7K0XW8E",
  "market_id": "polymarket_invasion_xy",
  "platform": "polymarket",
  "signal_type": "cross_market_divergence",
  "magnitude": 0.62,
  "direction": -1,
  "confidence": 0.66,
  "fdr_adjusted": true,
  "detected_at": "2026-04-15T09:45:00Z",
  "window_seconds": 14400,
  "liquidity_tier": "mid",
  "manipulation_flags": [],
  "related_market_ids": ["polymarket_unsc_session_xy"],
  "raw_features": {
    "spearman_current": 0.18,
    "spearman_historical_4h": 0.71,
    "fisher_z_distance": 0.78,
    "bh_p_value": 0.012,
    "calibration_provenance": "cross_market_fisher_bh_v1@curve_v1.3"
  },
  "schema_version": "1.0.0"
}
```

### `SignalContext`

```json
{
  "signal": { "...as above..." },
  "market_question": "Will Country X invade Country Y before July 2026?",
  "resolution_criteria": "Resolves YES if a recognized invasion of Country Y by Country X is reported by at least two of Reuters, AP, AFP before 2026-07-01.",
  "resolution_source": "Reuters, AP, AFP",
  "closes_at": "2026-07-01T00:00:00Z",
  "related_markets": [
    {"market_id": "polymarket_unsc_session_xy", "question": "Will the UN Security Council hold an emergency session on Country X before July 2026?", "current_price": 0.78, "delta_24h": 0.13, "volume_24h": 72000, "relationship_type": "positive", "relationship_strength": 0.71}
  ],
  "investigation_prompts": [
    "Search for diplomatic statement trackers on Country X in the last 48 hours",
    "Check sanctions enforcement actions announced in the last 7 days",
    "Review oil futures movement consistent or inconsistent with reduced invasion probability",
    "Check whether either market has experienced a single-counterparty trade large enough to explain the move"
  ],
  "interpretation_mode": "deterministic",
  "schema_version": "1.0.0"
}
```

### Consumer Verification Path

A `geopolitical_research_agent` receives the brief and follows the prompts:

1. Diplomatic statement tracker shows a multilateral framework was proposed in the last 24 hours.
2. Sanctions trackers show no new sanctions; supports the diplomatic-progress reading on the UNSC market.
3. Oil futures are stable; consistent with the invasion-probability decline.
4. The fourth prompt is precautionary — the agent checks for single-counterparty trades and finds normal distribution.

The agent concludes the divergence is more likely a real reflection of diplomatic activity than a mispricing. The agent prepares a brief for the foreign-policy desk citing the framework proposal.

### Why This Is a Positive Path

Augur surfaced a relationship-graph anomaly that a single-market view would not have caught. The divergence is a structured pointer to "these two markets are inconsistent — investigate why." The investigation prompts include a precautionary check against the most plausible alternative explanation (manipulation), and the agent uses it. Augur did not claim what was happening geopolitically; it pointed at the inconsistency, and the agent verified.

---

## Example 3 — Regime Exit on a Previously Dormant Crypto-Regulatory Market

### Scenario

The Polymarket contract `polymarket_solana_etf_dec2026` ("Will the SEC approve a Solana ETF by December 2026?") has traded in the 0.20 to 0.25 range for six weeks with low volume (median $32K daily, mid-tier). On a Monday morning, volatility triples over 24 hours and the price breaks to 0.38.

### Detection

The two-sided CUSUM regime-shift detector fires after the dormancy minimum (six hours of low-volatility precedence) is satisfied. The price velocity detector also fires. BH-FDR threshold passed. Manipulation detector evaluates and finds no matches; the move is broad-based across many counterparties. Calibrated confidence: 0.69.

### `MarketSignal`

```json
{
  "signal_id": "01HX4S2A4GMVB5C2KPN9XHTKP3",
  "market_id": "polymarket_solana_etf_dec2026",
  "platform": "polymarket",
  "signal_type": "regime_shift",
  "magnitude": 0.71,
  "direction": 1,
  "confidence": 0.69,
  "fdr_adjusted": true,
  "detected_at": "2026-04-13T11:18:00Z",
  "window_seconds": 86400,
  "liquidity_tier": "mid",
  "manipulation_flags": [],
  "related_market_ids": [
    "polymarket_btc_etf_inflows",
    "polymarket_eth_etf_dec2026",
    "kalshi_sec_enforcement_2026"
  ],
  "raw_features": {
    "cusum_positive": 12.4,
    "cusum_threshold": 10.0,
    "volatility_5m_now": 0.08,
    "volatility_5m_baseline": 0.025,
    "dormancy_seconds": 528000,
    "calibration_provenance": "regime_shift_cusum_adaptive_v1@curve_v1.3"
  },
  "schema_version": "1.0.0"
}
```

### `SignalContext`

```json
{
  "signal": { "...as above..." },
  "market_question": "Will the SEC approve a Solana ETF by December 2026?",
  "resolution_criteria": "Resolves YES if the SEC issues an order approving a spot Solana ETF for listing on a US exchange before 2026-12-31.",
  "resolution_source": "SEC orders published on sec.gov",
  "closes_at": "2026-12-31T23:59:59Z",
  "related_markets": [
    {"market_id": "polymarket_btc_etf_inflows", "question": "Will Bitcoin spot ETF net inflows exceed $1B in any week in 2026?", "current_price": 0.74, "delta_24h": 0.02, "volume_24h": 480000, "relationship_type": "positive", "relationship_strength": 0.6},
    {"market_id": "polymarket_eth_etf_dec2026", "question": "Will an Ethereum spot ETF be approved by December 2026?", "current_price": 0.81, "delta_24h": 0.04, "volume_24h": 220000, "relationship_type": "positive", "relationship_strength": 0.7},
    {"market_id": "kalshi_sec_enforcement_2026", "question": "Will the SEC announce more than 50 enforcement actions in 2026?", "current_price": 0.62, "delta_24h": -0.01, "volume_24h": 45000, "relationship_type": "inverse", "relationship_strength": 0.4}
  ],
  "investigation_prompts": [
    "Search SEC EDGAR for filings under issuer keywords in last 7 days",
    "Check CFTC enforcement action calendar",
    "Pull recent Congressional hearing transcripts on digital assets",
    "Check whether crypto-news outlets have surfaced relevant filings or rumors in the last 48 hours"
  ],
  "interpretation_mode": "deterministic",
  "schema_version": "1.0.0"
}
```

### Consumer Verification Path

A `crypto_research_agent` follows the prompts:

1. SEC EDGAR search for "Solana" returns three S-1 amendments filed in the last 5 days by major issuers.
2. CFTC enforcement calendar is empty for the next month.
3. Recent hearing transcripts include a House Financial Services subcommittee that discussed altcoin ETF treatment.
4. Crypto news outlets have not yet covered the EDGAR filings.

The agent identifies the EDGAR filings as the proximate trigger and prepares a brief for the regulatory news desk. Augur compressed the latency from EDGAR filing to editorial awareness from "next press cycle" to "minutes."

### Why This Is a Positive Path

Regime shift is the right signal type for this scenario — the market exited dormancy, and the detector caught it after the dormancy minimum. The investigation prompts directed the agent to a specific external source (EDGAR) where verifiable evidence exists. The agent's output cites the EDGAR filings, not Augur. Augur played its proper role: tip-generator, not source-of-truth.

---

## Example 4 — Election-Cycle High-Liquidity Move with Multiple Detectors Firing

### Scenario

During a US presidential primary cycle, the Polymarket contract `polymarket_primary_state_x_apr` ("Will Candidate Y win the Country X primary on April 23?") trades at 0.62. Over a 90-minute window, the price moves to 0.74 on 5× normal volume after a televised debate. The contract is in the `high` liquidity tier ($1.2M daily volume).

### Detection

Within the 90-minute window:

- The price velocity detector fires.
- The volume spike detector fires.
- The book imbalance detector fires (sustained bullish ratio with depth above floor).

The dedup layer's same-fingerprint dedup compresses the price velocity and volume spike signals (same market, similar buckets). The book imbalance signal stays separate (different signal type). The cluster merge with `polymarket_primary_state_x_april_runner_up` (inverse-relationship market that fell from 0.31 to 0.20) groups them into a single cluster-level signal.

Final emitted signal: one cluster signal of type `price_velocity` with related markets attached and the book imbalance signal as a separate item. Calibrated confidences: 0.79 (cluster) and 0.71 (book imbalance).

### `MarketSignal` (Cluster)

```json
{
  "signal_id": "01HX4WKQB9VJ8C6JP2TE4P2F5N",
  "market_id": "polymarket_primary_state_x_apr",
  "platform": "polymarket",
  "signal_type": "price_velocity",
  "magnitude": 0.83,
  "direction": 1,
  "confidence": 0.79,
  "fdr_adjusted": true,
  "detected_at": "2026-04-22T22:30:00Z",
  "window_seconds": 5400,
  "liquidity_tier": "high",
  "manipulation_flags": [],
  "related_market_ids": ["polymarket_primary_state_x_april_runner_up"],
  "raw_features": {
    "drift_pct": 0.19,
    "volume_ratio_5m": 5.2,
    "cluster_member_signal_ids": ["01HX4WK1...", "01HX4WK2...", "01HX4WK3..."],
    "calibration_provenance": "price_velocity_bocpd_beta_v1@curve_v1.3"
  },
  "schema_version": "1.0.0"
}
```

### `SignalContext`

```json
{
  "signal": { "...as above..." },
  "market_question": "Will Candidate Y win the Country X primary on April 23?",
  "resolution_criteria": "Resolves YES if official primary results, certified by the state authority, declare Candidate Y the winner.",
  "resolution_source": "State election authority certification",
  "closes_at": "2026-04-24T06:00:00Z",
  "related_markets": [
    {"market_id": "polymarket_primary_state_x_april_runner_up", "question": "Will Candidate Z win the Country X primary on April 23?", "current_price": 0.20, "delta_24h": -0.11, "volume_24h": 410000, "relationship_type": "inverse", "relationship_strength": 0.95}
  ],
  "investigation_prompts": [
    "Identify the most recent televised debate or major candidate event in the last 24 hours",
    "Check polling aggregator updates published in the last 12 hours",
    "Review prior-cycle primary timing for analogous reference base rates",
    "Check whether any single counterparty contributed disproportionately to the move"
  ],
  "interpretation_mode": "deterministic",
  "schema_version": "1.0.0"
}
```

### Consumer Verification Path

A `financial_news_desk` (covering political-event impacts on markets) receives the cluster brief:

1. The desk identifies the debate that ended 30 minutes before the signal.
2. Polling aggregators show a 2-point increase consistent with the price move.
3. Historical base rates show debate-driven moves typically persist for 12 to 36 hours.
4. The desk verifies no single-counterparty pattern is present.

The desk publishes a wire story citing the debate, the polling reaction, and the prediction-market response. Augur did not write the story; Augur prioritized which market to look at.

### Why This Is a Positive Path

Multiple detectors firing on the same underlying event is the right behavior. Dedup correctly compressed the redundant signals. The cluster captured the inverse-relationship market without the consumer needing to fetch it separately. The investigation prompts include a precautionary check (single-counterparty contribution), which is how Augur encodes operational discipline without making causal claims. The desk got a tip and produced a story; Augur stayed in its role.

---

## Common Properties of These Examples

1. The market is in the `high` or `mid` liquidity tier — Augur's covered scope.
2. The calibrated confidence is between 0.65 and 0.80, reflecting the typical empirical precision of these detector types.
3. The manipulation flags are empty — when a flag would be present, see `./negative-paths.md`.
4. The investigation prompts direct the consumer to specific external sources, not to interpret the signal directly.
5. No example contains a sentence asserting why the market moved. Augur reports the change; consumers do the interpretation.

The pattern of value delivery is consistent: Augur compresses the latency between a market move and the consumer's awareness of it, and provides structured pointers for verification. The consumer verifies and produces the explanation.
