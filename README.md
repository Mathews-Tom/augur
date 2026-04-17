# Augur

Structured market anomaly detection for prediction markets. Augur observes Polymarket and Kalshi with adaptive polling, extracts typed signals with calibrated confidence, and attaches investigation prompts drawn from a frozen library. The canonical consumer interface is a JSON schema; deterministic Markdown and a gated, opt-in LLM formatter are built on top of it.

Augur is not a forecaster, an arbitrage engine, or a news writer. It is a deterministic structured-signal pipeline. See `docs/foundations/overview.md` for the full product framing and `docs/foundations/non-goals.md` for what Augur explicitly does not do.

## Documentation

Authoritative documentation lives in `docs/`:

- `docs/foundations/` — overview, pitch, glossary, non-goals, open questions
- `docs/contracts/` — schemas, versioning policy, consumer registry
- `docs/methodology/` — calibration, manipulation taxonomy, labeling protocol
- `docs/architecture/` — system design, polling spec, deduplication and storms, storage and scaling
- `docs/examples/` — worked positive and negative signal paths
- `docs/strategy/` — risk register, defensibility thesis

Start with `docs/README.md` for the documentation index.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) 0.6 or newer for dependency management

## Local Development

```bash
git clone <repo>
cd augur
uv sync                          # resolves and installs all workspace dependencies
uv run pre-commit install        # install git hooks that mirror the CI gates
uv run pytest                    # run the test suite with coverage
```

All three workspace packages — `augur-signals`, `augur-labels`, `augur-format` — are installed in editable mode by `uv sync`. Configuration lives under `config/`; data and label artifacts live under `data/` and `labels/`. Exported JSON schemas are committed to `schemas/` and kept in sync by `scripts/export_schemas.py`.

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

```
augur/
├── pyproject.toml          # uv workspace root
├── uv.lock
├── config/                 # TOML configuration
├── data/                   # market taxonomy, investigation prompts, calibration state
├── labels/                 # newsworthy-event labels (Parquet)
├── schemas/                # exported JSON schemas per Pydantic model
├── scripts/                # export_schemas, backtest, calibrate, label
├── src/
│   ├── augur_signals/      # signal extraction core (no LLM imports — CI enforced)
│   ├── augur_labels/       # labeling pipeline
│   └── augur_format/       # deterministic and gated-LLM formatters
├── tests/
└── ops/                    # deployment and observability assets (populated later)
```

## License

See `LICENSE`.
