# Manual Testing Guide

Augur has three runnable surfaces today: the test suite, the labeling CLI, and the distributed-runtime smoke stack. This document enumerates what can be exercised locally and what remains operator-wiring work.

## 1. Quality gates and tests

Every commit must pass the same gates CI runs:

```bash
uv sync                               # install workspace + dev extras
uv run pre-commit install             # wire git hooks
uv run pytest                         # full suite with coverage
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src/
uv run python scripts/export_schemas.py --check
```

Targeted runs:

```bash
uv run pytest tests/signals/ -q                     # phase 1 + 2 + 5 unit layer
uv run pytest tests/format/ -q                      # phase 3 + 4 formatters
uv run pytest tests/labels/ -q                      # phase 2 pipeline
uv run pytest -m unit                               # fast unit subset
uv run pytest -m integration                        # opt-in; needs compose stack
```

## 2. Labeling CLI

The one end-to-end workflow that runs today is the annotator tool from phase 2.

```bash
uv run python scripts/label.py --help
uv run python scripts/label.py candidates                # list candidate events
uv run python scripts/label.py decide <candidate-id>     # record decision
uv run python scripts/label.py promote <event-id>        # gate through two-annotator rule
uv run python scripts/label.py coverage                  # per-category coverage
```

State persists to `labels/queue.json` and promoted rows land as partitioned Parquet under `labels/newsworthy_events/date=YYYY-MM-DD/`.

## 3. Distributed-runtime smoke stack

The phase 5 compose stack brings up every external dependency the workers need: NATS JetStream, Redis, TimescaleDB, Prometheus, and (optionally) an OTel collector. Workers run as separate host processes so each one is inspectable.

### Start infrastructure

```bash
docker compose -f ops/docker/compose.yaml up -d
docker compose -f ops/docker/compose.yaml ps
```

### Point workers at the smoke config

```bash
export AUGUR_CONFIG_DIR=$(pwd)/ops/docker/config
export AUGUR_TIMESCALE_URL=postgresql://augur:augur@localhost:5432/augur
export AUGUR_REPLICA_ID=$(hostname)-local
```

### Initialize the TimescaleDB schema

Run the monolith's migration script against the compose database to create hypertables + policies:

```bash
uv run python -c "
import asyncio
import os
import psycopg
from augur_signals._config import load_config
from augur_signals.storage._config import StorageConfig
from augur_signals.storage.factory import make_timescaledb_store
from pathlib import Path

async def init() -> None:
    cfg = load_config(Path('ops/docker/config/storage.toml'), StorageConfig)
    async with await psycopg.AsyncConnection.connect(os.environ['AUGUR_TIMESCALE_URL']) as conn:
        store = await make_timescaledb_store(cfg, connection=conn)
        await store.initialize()

asyncio.run(init())
"
```

### List worker entrypoints

```bash
uv run python -m augur_signals.workers
```

Output:

```
  poller           python -m augur_signals.workers.poller --platform <polymarket|kalshi>
  feature          python -m augur_signals.workers.feature --shard <index>/<count>
  detector         python -m augur_signals.workers.detector --shard <index>/<count>
  manipulation     python -m augur_signals.workers.manipulation
  calibration      python -m augur_signals.workers.calibration
  dedup            python -m augur_signals.workers.dedup
  context_format   python -m augur_signals.workers.context_format
```

### Current worker status

| Worker | Entrypoint state |
| --- | --- |
| `workers` (catalog) | Runnable — prints the list above |
| `poller` | Bootstrapped; requires `SnapshotSource` from `augur_signals.ingestion` to be wired by the deployment's bootstrap module. `python -m augur_signals.workers.poller --help` shows argparse; invocation exits with the wiring requirement. |
| `feature` / `detector` / `manipulation` / `calibration` / `dedup` / `context_format` / `augur_format.workers.llm` | **Deferred** — bus message-schema per subject (e.g., is an `augur.candidates.*` payload a raw `MarketSignal`, or a `MarketSignal` plus recent trades and book events?) is not fixed by the Phase 5 spec. A follow-up commit must: (1) define `BusMessage` payloads per subject, (2) expose the Phase 1-4 transforms (FeaturePipeline, DetectorRegistry, ManipulationDetector, Calibration, ClusterMerge, ContextAssembler, LLMInterpreter) behind a bus-friendly API with state persistence, (3) write per-kind `__main__.py` wrappers that load the transform via `augur_signals.workers.bootstrap`. |

### Bootstrap helpers (already runnable)

The bootstrap module is complete and covered by `tests/signals/test_worker_bootstrap.py`:

```python
from augur_signals.workers.bootstrap import (
    load_runtime_configs,
    activate_observability,
    build_event_bus,
    resolve_replica_id,
    parse_shard_arg,
)

cfg = load_runtime_configs()                          # from $AUGUR_CONFIG_DIR
activate_observability(cfg.observability)             # prometheus listener + OTel tracer
bus = build_event_bus(cfg.bus)                        # nats or redis
await bus.connect()
```

## 4. Migration scripts

Both scripts are fully runnable against the smoke stack once TimescaleDB is initialized.

### Backfill from the Parquet archive

```bash
uv run python scripts/migrate_to_timescale.py backfill \
    --from labels/snapshots_archive \
    --batch-size 10000
```

The script enumerates partitions chronologically, rejects partitions with unexpected columns, and aborts on row-count parity failure.

### Verify per-(market, day) parity

```bash
uv run python scripts/migrate_to_timescale.py verify \
    --start 2026-01-01 \
    --end 2026-04-01 \
    --duckdb data/augur.duckdb
```

### Dual-write sidecar

```bash
uv run python scripts/dual_write_sidecar.py \
    --lag-alert-seconds 10 \
    --bus-backend nats \
    --tee-subject augur.writes
```

Requires the engine to publish to `augur.writes` — this path is not wired in the monolith yet, so the sidecar is smoke-testable against handcrafted fixtures for now.

## 5. Container build and Kubernetes

### Build the image

```bash
docker build -f ops/docker/Dockerfile -t augur:dev .
```

The multi-stage build copies the uv venv + source + `config/` into a non-root user and exposes the monolith engine as the default CMD. Per-worker launch is a `CMD` override in the Kubernetes manifests.

### Dry-run the Kubernetes manifests

```bash
kubectl apply -k ops/deploy/ --dry-run=client -o yaml | less
```

Populate `ConfigMap` and `Secret` data before a real apply:

```bash
kubectl -n augur create configmap augur-config \
    --from-file=config/ \
    --dry-run=client -o yaml | kubectl apply -f -

kubectl -n augur create secret generic augur-secrets \
    --from-literal=AUGUR_TIMESCALE_URL="$AUGUR_TIMESCALE_URL" \
    --from-literal=REDIS_URL="redis://redis:6379/0" \
    --dry-run=client -o yaml | kubectl apply -f -
```

## 6. Observability

- Prometheus: `http://localhost:9090` after compose is up. Scrapes `host.docker.internal:9091..9097`.
- NATS admin: `http://localhost:8222/varz`.
- Redis CLI: `redis-cli -h localhost ping`.
- TimescaleDB: `psql $AUGUR_TIMESCALE_URL -c 'select * from timescaledb_information.hypertables'`.
- OTel collector: spans print to the container stdout (`docker compose logs otel-collector`).

## 7. Tear down

```bash
docker compose -f ops/docker/compose.yaml down -v
unset AUGUR_CONFIG_DIR AUGUR_TIMESCALE_URL AUGUR_REPLICA_ID
```

## 8. Known gaps

- No end-to-end monolith launcher (`python -m augur_signals.engine` has no `__main__`). The engine is driveable from Python and from `tests/signals/test_engine_integration.py`, but no production script.
- `scripts/backtest.py` and `scripts/calibrate.py` are stubs that raise `NotImplementedError`.
- Worker entrypoints for feature / detector / manipulation / calibration / dedup / context_format / llm require the bus message-schema work described in §3 above.
- Live failover tests against a real NATS or Redis cluster are operator-owned; CI uses dependency-injected fakes.
