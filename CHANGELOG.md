# Changelog

All notable changes to Augur are recorded in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with entries grouped by operational change per `.docs/DEVELOPMENT-PLAN.md §10`. Schema changes are cross-referenced to the relevant entry in `docs/contracts/schema-and-versioning.md`.

## [Unreleased]

### Added — Gated LLM Secondary Formatter

- `src/augur_format/llm/` package — the only location in the codebase where LLM SDK imports live, complementing the CI grep guard over `src/augur_signals/`.
- Expanded `IntelligenceBrief` contract with `headline` (≤ 90 chars), `body_markdown` (≤ 800 chars), `formatter_version`, `generated_at`, and model validators locking `interpretation_mode="llm_assisted"` and `forbidden_token_check="passed"`. Schema re-exported at `schemas/IntelligenceBrief-1.0.0.json`.
- `AbstractLLMBackend` protocol with two concrete adapters: `OllamaBackend` (plain httpx against the local daemon) and `AnthropicBackend` (lazy-imported anthropic SDK). Both accept retry budgets and raise `BackendError` on exhaustion.
- Deterministic `PromptBuilder` producing `(system, user)` prompt pairs with the sorted forbidden-phrase list, `IntelligenceBrief` schema summary, `ConsumerType` enum, and per-signal-type templates. Templates live under `augur_format/llm/prompts/templates/` and ship in the wheel.
- `ForbiddenTokenLinter` with `load_forbidden_phrases` that flattens every `[category].phrases` block in `config/forbidden_tokens.toml`. Matching is case-insensitive; a matched phrase drops the brief before `IntelligenceBrief` construction.
- `SchemaValidator` wrapping Pydantic `IntelligenceBrief.model_validate` and returning a stable `ValidationResult`.
- `ProvenanceStamp` carrying model-backend pair, SHA-256 prompt hash, and installed `formatter_version`. Auditors reproduce the hash from the deterministic prompt output.
- `ConsumerGate` enforcing `accepts_llm_assisted` opt-in per `docs/contracts/consumer-registry.md`.
- `LLMInterpreter` orchestrator composing backend + prompt + linter + schema validator + stamp. `set_suspended` wires into the Phase-1 `StormController` so briefs stop generating under storm-mode pressure.
- `config/llm.toml` with `[interpreter] enabled=false` default, Ollama and Anthropic backend blocks, and the prompt template directory path.

### Operational Handoff — LLM Formatter

After merge an operator who edits `config/llm.toml` to set `enabled = true`, installs the chosen backend (`augur-format[llm-local]` for Ollama, `augur-format[llm-cloud]` for Anthropic), and provisions any required credentials (`ANTHROPIC_API_KEY`) receives LLM-rendered briefs alongside the deterministic JSON and Markdown — but only for consumers whose `accepts_llm_assisted = true`. The deterministic pipeline runs regardless of LLM state.

### Added — Deterministic Formatters

- `src/augur_format/deterministic/json_feed.py` — `to_canonical_json` emits UTF-8 JSON bytes with stable key ordering (top-level, signal block, related-market block), six-decimal float rounding (configurable), and Z-suffix UTC timestamps. Byte-identical across invocations.
- `src/augur_format/deterministic/severity.py` — pure `derive_severity` mapping magnitude × confidence against per-liquidity-tier thresholds to `{high, medium, low}`. Formula lives in code so consumers can reproduce locally.
- `src/augur_format/deterministic/markdown.py` — Jinja2 `MarkdownFormatter` rendering five per-signal-type templates that extend `_base.md.j2`. Templates ship inside the wheel via the hatch `include = ["augur_format/**/*.j2"]` rule.
- `src/augur_format/validate/` — `ConsumerEnumValidator` rejects briefs whose `actionable_for` contains values outside `ConsumerType`; `load_schema` reads exported JSON schemas from `schemas/` for debug-build validation.
- `src/augur_format/transport/webhook.py` — `WebhookFormatter` POSTs canonical JSON, wrapped Markdown, or Slack Block Kit payloads to configured destinations with exponential-backoff retry on 5xx/429 and drop on 4xx. Auth headers sourced from env vars at delivery time.
- `src/augur_format/transport/websocket.py` — `WebSocketBroadcaster` with `SIGNAL`, `HEARTBEAT`, `STORM_START`, `STORM_END` frame types; oldest-drop under full per-connection queues for timeliness under pressure.
- `src/augur_format/routing/` — `ConsumerRegistry.from_toml` loads `config/consumers.toml` and exposes per-category routing; `SignalRouter` maps `SignalContext` to the consumer set, surfacing suppressed consumers for `llm_assisted` interpretation mode.
- `src/augur_format/llm/models.py` — `IntelligenceBrief` contract declared in this phase for completeness. The gated LLM formatter in the next phase instantiates the model; the JSON schema ships at `schemas/IntelligenceBrief-1.0.0.json`.
- `config/formatters.toml` mirrors `phase-3 §12.2` with JSON, Markdown, Webhook, and WebSocket blocks validated against `FormatterConfig`.

### Operational Handoff — Deterministic Formatters

After merge operators can subscribe clients to the WebSocket broadcaster for live signal frames, wire webhook targets (Slack or generic JSON/Markdown) to push brief deliveries, and route signals to consumers via the `ConsumerRegistry` loaded from `config/consumers.toml`. The canonical JSON feed is ready for any consumer that validates against `schemas/SignalContext-1.0.0.json`.

### Added — Labeling Pipeline

- `src/augur_labels/` package with Pydantic data contracts for `NewsworthyEvent`, `EventCandidate`, `SourcePublication`, `QualifyingSource`, `LabelDecision`, `AnnotatorIdentity`, and `AgreementReport`. The closed `source_id` literal set (reuters, bloomberg, ap, ft) is load-bearing across adapters, storage, and workflow.
- Four source adapters (`ReutersAdapter`, `BloombergAdapter`, `ApAdapter`, `FtAdapter`) implementing `AbstractSourceAdapter` against their respective REST APIs with shared exponential-backoff retry. Credentials are read from the env vars documented in `docs/methodology/labeling-protocol.md`; missing credentials fail loud at construction except for the FT adapter, which gracefully degrades to empty output on missing API key.
- Append-only Parquet writer with per-date partitioning and `filelock`-based concurrent-write safety. `supersede()` implements the protocol's correction path in-place under the partition lock. `LabelReader` exposes `events_in_window`, `events_for_market`, and `coverage_by_category` with partition pruning.
- Inter-annotator agreement metrics via Cohen's kappa on event existence and category assignment, 60-second timestamp agreement, and mean market-association Jaccard. `compute_agreement` pairs decisions by `candidate_id` and evaluates the four targets from `docs/methodology/labeling-protocol.md §Inter-Annotator Agreement`.
- `WorkflowEnforcer.can_promote` and `promotion_warnings` enforce the two-annotator promotion gate: two distinct annotators, existence agreement, timestamp within 5-minute hard fail, and strictly positive market Jaccard.
- `join_signals_to_events` implements the canonical TP/FP criteria: market_id match plus lead time in (0, 24h]. Multiple events on the same market match the earliest qualifying one; non-labeled statuses (candidate, superseded, rejected) are excluded.
- Click-driven `augur-label` CLI with `candidates`, `inspect`, `decide`, `promote`, `correct`, and `coverage` commands. The CLI persists queue state to `labels/queue.json` and writes promoted events to the parquet corpus.
- `config/labeling.toml` mirrors `docs/methodology/labeling-protocol.md` defaults (rate limits, agreement targets, storage paths, join windows).

### Operational Handoff — Labeling

After merge a labeler can run `augur-label candidates`, `augur-label decide`, and `augur-label promote` against real candidates. The nightly calibration job (Phase 1's `scripts/calibrate.py`) consumes `join_signals_to_events` output to rebuild reliability curves. The first 90 days of operation require double labeling per `docs/methodology/labeling-protocol.md §Inter-Annotator Agreement`; CI reports agreement metrics during that window.

### Added

- Pydantic data contracts: `MarketSnapshot`, `FeatureVector`, `MarketSignal`, `SignalContext`, `RelatedMarketState`, and the closed enums `SignalType`, `ManipulationFlag`, `ConsumerType`, `InterpretationMode`. `MarketSignal` enforces `calibration_provenance` via a model validator; every model is frozen and rejects unknown fields. JSON schemas exported to `schemas/*.json` and kept in sync by `scripts/export_schemas.py`.
- Ingestion layer: `AbstractPoller` protocol with `PolymarketPoller` and `KalshiPoller` concrete implementations against the REST APIs, exponential-backoff retry helper, and the normalizer that maps raw platform payloads onto `MarketSnapshot` with verbatim preservation of question / resolution_source / resolution_criteria.
- Adaptive polling scheduler implementing the four-tier state machine (hot/warm/cool/cold) with hysteresis bands and rate-limit-pressure-driven demotion per `docs/architecture/adaptive-polling-spec.md`.
- Feature pipeline with per-market `SnapshotBuffer`, halt-aware EWMA baseline (alpha 0.05), and the momentum / volatility / volume-ratio / bid-ask / spread indicators computed over the canonical 5m / 15m / 1h / 4h windows. Windows are observation-count internally so tier changes do not corrupt feature semantics.
- Five detectors: price velocity (Bernoulli-Beta BOCPD against running-mean projections), volume spike (EWMA z-score), book imbalance (depth-gated with persistence), regime shift (two-sided CUSUM with dormancy gate), cross-market divergence (Spearman + Fisher-z + BH-FDR). Every detector threads `now` as a parameter and enforces the 6 h pre-resolution exclusion inside `ingest`.
- Manipulation signature catalogue (Herfindahl concentration, size-vs-depth outlier, cancel-replace burst, thin-book-during-move, pre-resolution window) plus the `ManipulationDetector` aggregator and the curated `CURATED_EPISODES` fixtures with expected flag sets.
- Calibration layer: Benjamini-Hochberg FDR controller, reliability-curve analyzer with an identity placeholder curve, empirical FPR computation against a labeled event stream, drift monitor with PSI and KS metrics, liquidity-tier banding.
- DuckDB storage with schema migrations for snapshots, features, signals, manipulation flags, calibration FPR, and reliability curves; typed round-trip between the frozen Pydantic models and the database.
- In-process async bus, fingerprint deduplication, taxonomy-clustered merge, and the storm-mode state machine with hysteresis between trigger and recovery thresholds.
- Context assembly layer: `MarketTaxonomy` with bidirectional edge lookup, frozen `InvestigationPromptLibrary` with coverage reporting, `RelatedMarketResolver`, and the deterministic `ContextAssembler` whose output is byte-identical on repeated invocations.
- `Engine` orchestrator composing the full pipeline and the `scripts/lint_detector_now.py` AST guard against `datetime.now()` usage inside detector modules. The guard is wired into pre-commit and CI.
- Four JSON schemas exported to `schemas/`: `MarketSnapshot-1.0.0.json`, `FeatureVector-1.0.0.json`, `MarketSignal-1.0.0.json`, `SignalContext-1.0.0.json`.

### Operational Handoff

Live signal extraction is operational against Polymarket and Kalshi once API credentials are provisioned (`KALSHI_API_KEY`) and `config/markets.toml` populated with the watchlist. Signals persist to DuckDB and the backtest harness can replay historical snapshots through the same code paths.

## [0.0.0] — 2026-04-17

### Added

- Initial project scaffolding: uv workspace with three member packages (`augur-signals`, `augur-labels`, `augur-format`), pinned dev tooling (ruff, mypy, pytest, hypothesis, pre-commit, structlog), and locked transitive dependencies.
- Placeholder TOML configuration under `config/` for engine defaults, market watchlist, detector parameters, polling, deduplication, consumer routing, and forbidden-token vocabulary. Parameter values mirror the documented defaults in `docs/architecture/adaptive-polling-spec.md`, `docs/architecture/deduplication-and-storms.md`, and `docs/contracts/consumer-registry.md`.
- Configuration loader with Pydantic validation, structured JSON logging via structlog, and no-op observability primitives (`MetricCounter`, `MetricGauge`, `trace_span`) that future runtime commits swap for real Prometheus and OpenTelemetry adapters.
- `scripts/export_schemas.py` tool with `--check` mode for CI drift detection. Entrypoint stubs for `backtest.py`, `calibrate.py`, and `label.py` raise `NotImplementedError` until their workstreams land.
- Pre-commit hooks and a GitHub Actions workflow mirroring the same gate surface: ruff lint and format, mypy strict, LLM-import guard over `src/augur_signals/`, forbidden-token doc lint over `docs/`, secret scan, schema export check, and pytest with coverage.
- `commitlint.config.js` enforcing conventional commit format on pull-request titles.

### Operational Handoff

The repository is scaffolded but not operational: no application logic, no live connections, no observable behavior. `uv sync && uv run pytest` produces a green pipeline on a clean clone.
