# Changelog

All notable changes to Augur are recorded in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with entries grouped by operational change per `.docs/DEVELOPMENT-PLAN.md §10`. Schema changes are cross-referenced to the relevant entry in `docs/contracts/schema-and-versioning.md`.

## [Unreleased]

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
