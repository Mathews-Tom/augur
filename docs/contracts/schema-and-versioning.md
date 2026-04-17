# Schema and Versioning

This document is the canonical source for every cross-layer data contract in Augur. Any field referenced anywhere else in the documentation must match the definitions here. Schemas are versioned; the current version is `1.0.0`.

## Closed Enums

Every consumer-facing string field is constrained to a closed enum. Adding members requires a schema-version bump and a migration note. Free-form strings outside these enums are not valid output.

### `SignalType`

| Value                     | Meaning                                                                                                       |
| ------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `price_velocity`          | Statistically significant change in market price detected by Beta-Binomial BOCPD.                             |
| `volume_spike`            | Volume above the FDR-controlled threshold relative to the EWMA baseline.                                      |
| `book_imbalance`          | Sustained bid/ask depth imbalance above threshold with sufficient total depth.                                |
| `cross_market_divergence` | Spearman correlation between related markets diverges from historical, passing Benjamini-Hochberg correction. |
| `regime_shift`            | Two-sided CUSUM on volatility crosses threshold after a minimum dormancy period.                              |

### `ManipulationFlag`

| Value                               | Meaning                                                                                   |
| ----------------------------------- | ----------------------------------------------------------------------------------------- |
| `single_counterparty_concentration` | One counterparty's volume share exceeds the Herfindahl threshold within the trade window. |
| `size_vs_depth_outlier`             | A single trade consumed more than the configured fraction of resting depth.               |
| `cancel_replace_burst`              | Cancel-replace event count exceeded threshold within the burst window.                    |
| `thin_book_during_move`             | Median book depth during the move was below the minimum-depth floor.                      |
| `pre_resolution_window`             | Signal occurred within the six-hour pre-resolution exclusion window.                      |

### `ConsumerType`

Closed enum. The full list, with routing semantics for each, is in `./consumer-registry.md`. Members at schema version 1.0.0:

```
macro_research_agent
geopolitical_research_agent
crypto_research_agent
financial_news_desk
regulatory_news_desk
dashboard
```

### `InterpretationMode`

| Value           | Meaning                                                                                                        |
| --------------- | -------------------------------------------------------------------------------------------------------------- |
| `deterministic` | Output produced by the context assembler or a template-based formatter. No LLM involvement.                    |
| `llm_assisted`  | Output produced by the optional LLM formatter. Restricted vocabulary applied. Provenance stamped on the brief. |

## `MarketSnapshot`

A normalized, platform-agnostic representation of a market's state at a single observation. Produced by the normalizer from raw platform responses.

```python
class MarketSnapshot(BaseModel, frozen=True):
    market_id: str
    platform: Literal["polymarket", "kalshi"]
    timestamp: datetime              # UTC
    last_price: float                # in [0, 1]
    bid: float | None
    ask: float | None
    spread: float | None
    volume_24h: float                # USD
    liquidity: float                 # USD; total resting depth (top 5 levels)
    question: str                    # verbatim from platform
    resolution_source: str | None    # verbatim
    resolution_criteria: str | None  # verbatim
    closes_at: datetime | None
    raw_json: dict                   # full platform response, retained for replay
    schema_version: Literal["1.0.0"]
```

## `FeatureVector`

The output of the feature pipeline for a single market at a single computation tick.

```python
class FeatureVector(BaseModel, frozen=True):
    market_id: str
    computed_at: datetime
    price_momentum_5m: float
    price_momentum_15m: float
    price_momentum_1h: float
    price_momentum_4h: float
    volatility_5m: float
    volatility_15m: float
    volatility_1h: float
    volatility_4h: float
    volume_ratio_5m: float           # window volume / EWMA baseline
    volume_ratio_1h: float
    bid_ask_ratio: float | None      # bid_depth / (bid_depth + ask_depth)
    spread_pct: float | None
    schema_version: Literal["1.0.0"]
```

## `MarketSignal`

The canonical structured event emitted by the signal extraction layer. Binding contract between extraction and context assembly.

```python
class MarketSignal(BaseModel, frozen=True):
    signal_id: str                          # uuid7, time-ordered
    market_id: str
    platform: Literal["polymarket", "kalshi"]
    signal_type: SignalType
    magnitude: float                        # detector-defined, range [0, 1]
    direction: Literal[-1, 0, 1]            # discrete
    confidence: float                       # empirical, from calibration layer, [0, 1]
    fdr_adjusted: bool                      # threshold passed BH-FDR control
    detected_at: datetime                   # UTC
    window_seconds: int
    liquidity_tier: Literal["high", "mid", "low"]
    manipulation_flags: list[ManipulationFlag]   # may be empty; never None
    related_market_ids: list[str]
    raw_features: dict[str, float]          # detector-specific debug payload
    schema_version: Literal["1.0.0"]
```

Field invariants:

- `confidence` MUST come from the calibration layer's reliability curve, not from raw detector posteriors. The constructor asserts that `raw_features["calibration_provenance"]` is non-empty.
- `direction` is an integer (-1, 0, or 1). Float values are rejected at the schema boundary.
- `manipulation_flags` is always present and always a list. Empty list means no signature matched; it does not mean manipulation has been ruled out.
- `liquidity_tier` is computed from a 7-day rolling volume window per `../foundations/glossary.md`. Tier reassignment happens daily.

JSON schema is exported to `schemas/MarketSignal-1.0.0.json` at build time. Consumers should validate against the exported schema, not against the Python model.

## `RelatedMarketState`

A snapshot of a related market at the time the context assembler runs.

```python
class RelatedMarketState(BaseModel, frozen=True):
    market_id: str
    question: str
    current_price: float
    delta_24h: float
    volume_24h: float
    relationship_type: Literal["positive", "inverse", "complex", "causal"]
    relationship_strength: float
```

## `SignalContext`

The deterministic envelope produced by the context assembler. Wraps a `MarketSignal` with verbatim platform metadata, related-market state, and curated investigation prompts. Contains no synthesized text.

```python
class SignalContext(BaseModel, frozen=True):
    signal: MarketSignal
    market_question: str                    # verbatim
    resolution_criteria: str                # verbatim
    resolution_source: str                  # verbatim
    closes_at: datetime
    related_markets: list[RelatedMarketState]
    investigation_prompts: list[str]        # curated, frozen at startup
    interpretation_mode: InterpretationMode # always DETERMINISTIC at this layer
    schema_version: Literal["1.0.0"]
```

The context assembler is a pure function modulo its inputs (signal, metadata store, taxonomy, prompt library). Two assembler invocations with identical inputs MUST produce byte-identical `SignalContext` JSON. Determinism tests enforce this.

## `IntelligenceBrief` (Phase 4 Contract, Gated)

The output of the optional LLM formatter. Declared here for completeness; not produced by the deterministic pipeline. Routing restrictions and the forbidden-token vocabulary are described in `../methodology/calibration-methodology.md`.

```python
class IntelligenceBrief(BaseModel, frozen=True):
    brief_id: str
    signal_id: str
    headline: str
    body_markdown: str
    severity: Literal["high", "medium", "low"]   # derived deterministically
    actionable_for: list[ConsumerType]            # closed enum, validated
    interpretation_mode: Literal["llm_assisted"]
    model: str                                    # model identifier
    prompt_hash: str                              # SHA-256 of resolved prompt
    forbidden_token_check: Literal["passed"]      # mandatory linter result
    schema_version: Literal["1.0.0"]
```

A brief whose `actionable_for` contains any value not in the `ConsumerType` enum is rejected at the formatter boundary. A brief that fails the forbidden-token check is rejected and never enters the bus.

## Versioning Policy

Schemas use semver (`major.minor.patch`).

| Change Type                                                          | Version Bump | Migration Required                                                          |
| -------------------------------------------------------------------- | ------------ | --------------------------------------------------------------------------- |
| Add a non-required field with a default                              | patch        | No                                                                          |
| Add a required field                                                 | minor        | Producer-side defaults; consumer should treat as optional during transition |
| Add a member to a closed enum                                        | minor        | Consumers must accept unknown enum values gracefully during transition      |
| Remove or rename a field, change a field type, remove an enum member | major        | All consumers must migrate; release notes are mandatory                     |

Every schema change is documented in a `CHANGELOG.md` entry alongside the JSON schema export. Producers stamp `schema_version` on every emitted message. Consumers validate `schema_version` and reject incompatible versions explicitly rather than coercing.

## Compatibility Matrix

| Producer Schema | Consumer Schema | Behavior                                                        |
| --------------- | --------------- | --------------------------------------------------------------- |
| 1.0.x           | 1.0.x           | Full compatibility                                              |
| 1.0.x           | 1.1.x           | Forward-compatible; consumer ignores unknown optional fields    |
| 1.1.x           | 1.0.x           | Backward-compatible only if 1.1.x changes are additive optional |
| Major mismatch  | —               | Rejected at validation; explicit migration required             |

## Consumer Migration Guidance

When a breaking schema change ships, consumers receive a release note describing:

1. Which fields changed.
2. Default values to assume during transition.
3. The earliest producer version that emits the new schema.
4. The latest producer version that emits the old schema.

Augur producers run both schemas in parallel during a deprecation window of at least 90 days for major changes.
