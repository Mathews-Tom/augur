# Changelog

All notable changes to Augur are recorded in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with entries grouped by operational change per `.docs/DEVELOPMENT-PLAN.md §10`. Schema changes are cross-referenced to the relevant entry in `docs/contracts/schema-and-versioning.md`.

## [Unreleased]

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
