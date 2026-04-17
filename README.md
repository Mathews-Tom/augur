# Augur

Structured market anomaly detection for prediction markets. Augur observes Polymarket and Kalshi with adaptive polling, extracts typed signals with calibrated confidence, and attaches investigation prompts drawn from a frozen library. The canonical consumer interface is a JSON schema; deterministic Markdown and a gated, opt-in LLM formatter are built on top of it.

Augur is not a forecaster, an arbitrage engine, or a news writer. It is a deterministic structured-signal pipeline. See `docs/foundations/overview.md` for the full product framing and `docs/foundations/non-goals.md` for what Augur explicitly does not do.

Current version: **0.1.0**. Phase 1-5 scaffolding landed; runnable surfaces are the test suite, the labeling CLI, and the distributed-runtime smoke stack. See `docs/operations/manual-testing.md` for the end-to-end guide.

## Documentation

Authoritative documentation lives in `docs/`:

- `docs/foundations/` — overview, pitch, glossary, non-goals, open questions
- `docs/contracts/` — schemas, versioning policy, consumer registry
- `docs/methodology/` — calibration, manipulation taxonomy, labeling protocol
- `docs/architecture/` — system design, polling spec, deduplication and storms, storage and scaling
- `docs/operations/` — distributed runbook, manual testing guide
- `docs/examples/` — worked positive and negative signal paths
- `docs/strategy/` — risk register, defensibility thesis

Start with `docs/README.md` for the documentation index.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) 0.6 or newer for dependency management
- Optional: Docker + Docker Compose for the phase-5 smoke stack

## Local Development

```bash
git clone <repo>
cd augur
uv sync                          # resolves and installs all workspace dependencies
uv run pre-commit install        # install git hooks that mirror the CI gates
uv run pytest                    # run the test suite with coverage
```

All three workspace packages — `augur-signals`, `augur-labels`, `augur-format` — are installed in editable mode by `uv sync`. Configuration lives under `config/`; data and label artifacts live under `data/` and `labels/`. Exported JSON schemas are committed to `schemas/` and kept in sync by `scripts/export_schemas.py`.

## Optional Dependency Groups

Each workspace package exposes extras for opt-in integrations. Install only what a deployment needs:

```bash
# LLM secondary formatter (phase 4)
uv sync --extra llm-local        # augur-format[llm-local] — Ollama client
uv sync --extra llm-cloud        # augur-format[llm-cloud] — Anthropic SDK

# Distributed runtime (phase 5)
uv sync --extra bus-nats         # NATS JetStream adapter
uv sync --extra bus-redis        # Redis Streams adapter
uv sync --extra storage-timescale # TimescaleDB via psycopg
uv sync --extra observability    # Prometheus + OpenTelemetry
uv sync --extra distributed      # all of the above
```

The dev dependency group in the repo root already pulls every extra so CI exercises every adapter against injected fakes.

## Runnable Surfaces

### Labeling CLI (phase 2)

```bash
uv run python scripts/label.py --help
uv run python scripts/label.py candidates
uv run python scripts/label.py decide <candidate-id>
```

### Worker entrypoints (phase 5)

```bash
uv run python -m augur_signals.workers                 # catalog
uv run python -m augur_signals.workers.poller --help   # per-kind entrypoints
```

The `workers` package exposes bootstrap helpers (`augur_signals.workers.bootstrap`) that every `__main__` module uses for config loading, observability activation, and bus connection. Per-kind transform wiring for feature / detector / manipulation / calibration / dedup / context_format / llm requires a follow-up commit — see `docs/operations/manual-testing.md §3`.

### Migration scripts (phase 5)

```bash
uv run python scripts/migrate_to_timescale.py backfill --from labels/snapshots_archive
uv run python scripts/migrate_to_timescale.py verify --start 2026-01-01 --end 2026-04-01 --duckdb data/augur.duckdb
uv run python scripts/dual_write_sidecar.py --lag-alert-seconds 10
```

### Smoke stack (phase 5)

```bash
docker compose -f ops/docker/compose.yaml up -d        # NATS + Redis + TimescaleDB + Prometheus
export AUGUR_CONFIG_DIR=$(pwd)/ops/docker/config
export AUGUR_TIMESCALE_URL=postgresql://augur:augur@localhost:5432/augur
```

### Container build

```bash
docker build -f ops/docker/Dockerfile -t augur:dev .
kubectl apply -k ops/deploy/ --dry-run=client -o yaml
```

## Quality Gates

The following commands must pass before any commit reaches `main`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src/
uv run pytest --cov=src --cov-fail-under=80
uv run python scripts/export_schemas.py --check
```

Coverage thresholds (80 % overall, 90 % new code, 95 % critical paths) follow `~/.claude/rules/test-standards.md`. Commit messages follow the conventional commit format in `~/.claude/rules/commit-standards.md`; commitlint is enforced on pull-request titles.

## Repository Layout

```text
augur/
├── pyproject.toml          # uv workspace root (v0.1.0)
├── uv.lock
├── config/                 # TOML configuration
│   ├── bus.toml            # phase 5 — message bus backend
│   ├── storage.toml        # phase 5 — DuckDB / TimescaleDB selector
│   ├── observability.toml  # phase 5 — Prometheus + OTel exporters
│   ├── llm.toml            # phase 4 — gated LLM formatter
│   └── ...                 # polling, detectors, dedup, formatters, consumers, labeling, markets, forbidden_tokens
├── data/                   # market taxonomy, investigation prompts, calibration state
├── labels/                 # newsworthy-event labels (Parquet)
├── schemas/                # exported JSON schemas per Pydantic model
├── scripts/
│   ├── backtest.py         # stub
│   ├── calibrate.py        # stub
│   ├── export_schemas.py
│   ├── label.py            # labeling CLI wrapper
│   ├── lint_detector_now.py
│   ├── migrate_to_timescale.py    # phase 5 backfill + verify
│   └── dual_write_sidecar.py      # phase 5 tee replay
├── src/
│   ├── augur_signals/      # signal extraction core (no LLM imports — CI enforced)
│   │   └── augur_signals/
│   │       ├── bus/        # EventBus protocol + NATS + Redis + distributed lock
│   │       ├── workers/    # harness, singleton runner, bootstrap, subject helpers
│   │       ├── storage/    # DuckDB + TimescaleDB adapters
│   │       └── ...         # ingestion, features, detectors, manipulation, calibration, dedup, context
│   ├── augur_labels/       # labeling pipeline (phase 2)
│   └── augur_format/       # deterministic and gated-LLM formatters (phases 3 + 4)
├── tests/
├── ops/
│   ├── docker/             # multi-stage Dockerfile + local compose smoke stack
│   │   ├── Dockerfile
│   │   ├── compose.yaml
│   │   ├── prometheus.yml
│   │   ├── otel-collector.yaml
│   │   └── config/         # smoke-specific bus/storage/observability TOMLs
│   └── deploy/             # Kubernetes manifests (Deployments, StatefulSets, HPA, Services)
└── .docs/                  # phase specs and development plan
```

## Phase Status

| Phase | Scope | State |
| --- | --- | --- |
| 0 | Project workspace, CI scaffolding | Merged |
| 1 | Signal extraction core, detectors, calibration, dedup, context | Merged |
| 2 | Labeling pipeline + annotator CLI | Merged |
| 3 | Deterministic formatters (JSON, Markdown, WebSocket, Webhook) | Merged |
| 4 | Gated LLM secondary formatter | Merged |
| 5 | Distributed runtime scaffolding (bus, TimescaleDB, workers, ops) | Merged |

`CHANGELOG.md` records per-phase operational handoff notes. Release notes for v0.1.0 will aggregate these on tag.

## License

See `LICENSE`.
