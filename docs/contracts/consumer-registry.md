# Consumer Registry

The `ConsumerType` enum is closed. Every value used in any `actionable_for` field, in any routing rule, or in any documentation example must be a member of this registry. Adding a member requires a schema-version bump and an entry below.

## Why This Is Closed

In the original design, the LLM formatter generated `actionable_for` strings freely. This produced two failure modes: (1) downstream routers received unknown consumer types and silently dropped briefs, and (2) the schema-as-de-facto-standard moat could not form because the schema was non-deterministic. The closed enum eliminates both.

## Current Members (Schema 1.0.0)

### `macro_research_agent`

A consumer focused on macroeconomic research: Federal Reserve decisions, inflation, employment, sovereign debt, currency markets. Routes to this consumer when the signal originates in markets categorized as `monetary_policy`, `inflation`, `employment`, `sovereign_debt`, or `currency`. The consumer expects briefs containing the resolution criteria text, the related-market state for adjacent macro contracts, and investigation prompts directing it to FOMC calendars, governor speeches, and recent economic releases.

### `geopolitical_research_agent`

A consumer focused on international relations, conflict, diplomatic activity, and sanctions. Routes to this consumer when the signal originates in markets categorized as `geopolitics`, `conflict`, `sanctions`, or `diplomatic`. The consumer expects briefs containing related-market state for adjacent geopolitical contracts (e.g., UN actions, oil prices, currency moves) and investigation prompts directing it to government statement trackers, sanctions lists, and treaty calendars.

### `crypto_research_agent`

A consumer focused on cryptocurrency regulation, ETF approvals, exchange enforcement, and major protocol events. Routes to this consumer when the signal originates in markets categorized as `crypto_regulatory`, `crypto_etf`, `crypto_enforcement`, or `crypto_protocol`. The consumer expects briefs containing related-market state for adjacent crypto contracts and investigation prompts directing it to SEC EDGAR filings, CFTC enforcement calendars, and protocol governance forums.

### `financial_news_desk`

A consumer with editorial responsibility for financial news coverage. Receives briefs from any market categorized as `monetary_policy`, `markets`, `corporate`, `m_and_a`, or `crypto_etf`. The consumer treats the brief as a tip, not a story; it does not publish without independent verification. The investigation prompts in the brief are the starting point for that verification.

### `regulatory_news_desk`

A consumer with editorial responsibility for regulatory and policy coverage. Receives briefs from any market categorized as `regulatory`, `crypto_regulatory`, `crypto_enforcement`, `monetary_policy`, or `sanctions`. The consumer treats the brief as a tip, not a story.

### `dashboard`

A human-facing real-time dashboard. Receives all briefs not gated by manipulation suppression policy and renders them as a live feed. The dashboard consumer is the only one that may receive `interpretation_mode = llm_assisted` briefs by default; all agent consumers receive `interpretation_mode = deterministic` unless they explicitly opt in.

## Routing Table

| Market Category      | Default Consumers                                                  |
| -------------------- | ------------------------------------------------------------------ |
| `monetary_policy`    | `macro_research_agent`, `financial_news_desk`, `dashboard`         |
| `inflation`          | `macro_research_agent`, `dashboard`                                |
| `employment`         | `macro_research_agent`, `dashboard`                                |
| `sovereign_debt`     | `macro_research_agent`, `financial_news_desk`, `dashboard`         |
| `currency`           | `macro_research_agent`, `dashboard`                                |
| `geopolitics`        | `geopolitical_research_agent`, `dashboard`                         |
| `conflict`           | `geopolitical_research_agent`, `dashboard`                         |
| `sanctions`          | `geopolitical_research_agent`, `regulatory_news_desk`, `dashboard` |
| `diplomatic`         | `geopolitical_research_agent`, `dashboard`                         |
| `crypto_regulatory`  | `crypto_research_agent`, `regulatory_news_desk`, `dashboard`       |
| `crypto_etf`         | `crypto_research_agent`, `financial_news_desk`, `dashboard`        |
| `crypto_enforcement` | `crypto_research_agent`, `regulatory_news_desk`, `dashboard`       |
| `crypto_protocol`    | `crypto_research_agent`, `dashboard`                               |
| `regulatory`         | `regulatory_news_desk`, `dashboard`                                |
| `markets`            | `financial_news_desk`, `dashboard`                                 |
| `corporate`          | `financial_news_desk`, `dashboard`                                 |
| `m_and_a`            | `financial_news_desk`, `dashboard`                                 |

Categories not in this table fall through to `dashboard` only.

## Validation

Every brief produced by any formatter passes through enum validation before emission. The formatter rejects any brief whose `actionable_for` list contains a string outside the enum members above. Rejection is loud — the brief is dropped and an error is logged with the offending string. The formatter never silently coerces unknown values.

The CI lint in `../README.md` greps the entire `docs/` tree for any `actionable_for` string that is not a registered member; the build fails on a hit.

## Addition Process

To add a consumer:

1. Open a pull request that adds the member to this file under "Current Members" with a description matching the existing entries' format, adds a row to the routing table, and adds the string to the `ConsumerType` enum in `./schema-and-versioning.md`.
2. Bump the schema minor version (additive change).
3. Add a `CHANGELOG.md` entry describing the addition and any new categories the consumer expects.
4. Update any affected examples in `../examples/`.
5. Update consumer-side routing in any deployment that consumes Augur's feed.

Removing a consumer requires a schema major-version bump and a 90-day deprecation window per the policy in `./schema-and-versioning.md`.

## Why Each Consumer Exists

| Consumer                      | Existence Rationale                                                                                                                                                   |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `macro_research_agent`        | Highest-liquidity Augur signals come from macro markets; a typed consumer prevents these from being misrouted to general dashboards.                                  |
| `geopolitical_research_agent` | Cross-market divergence signals are most valuable in geopolitical clusters; a typed consumer can act on the related-market state without losing it in a general feed. |
| `crypto_research_agent`       | Crypto markets have distinct manipulation profiles; a typed consumer can apply category-specific suppression policies.                                                |
| `financial_news_desk`         | Editorial workflow is fundamentally different from agent workflow; the typed consumer enables formatting differences (e.g., longer prose, citation prompts).          |
| `regulatory_news_desk`        | Regulatory coverage requires separate sourcing discipline from market coverage; the typed consumer keeps the workflows separate.                                      |
| `dashboard`                   | The catch-all human consumer; receives everything not explicitly gated. The only consumer that may receive LLM-assisted briefs by default.                            |
