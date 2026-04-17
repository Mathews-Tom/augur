# Storage and Scaling

This document specifies Augur's storage architecture, partitioning strategy, the explicit trigger for migrating from embedded DuckDB to a multi-process TimescaleDB deployment, and per-phase cost estimates. It supersedes the original "scaled future" handwave with measurable triggers.

## Phase 1 Storage — Embedded DuckDB

The MVP runs as a single asyncio process with embedded DuckDB. No separate database process. The schema is defined in `./system-design.md` Storage Schema. The DuckDB file lives at `~/.augur/data/augur.duckdb` with Parquet partitions for cold data.

### Capacity

| Metric                                               | Value                                                     |
| ---------------------------------------------------- | --------------------------------------------------------- |
| Markets tracked                                      | 100 to 150                                                |
| Snapshot rate                                        | One per market per polling tick (15 s to 300 s, adaptive) |
| Snapshot size                                        | ≈ 500 bytes including raw_json                            |
| Daily snapshot count (100 markets, 30 s avg cadence) | ≈ 290,000                                                 |
| Annual snapshot count                                | ≈ 105 million                                             |
| Annual on-disk footprint (compressed)                | ≈ 8 to 12 GB                                              |

DuckDB's columnar storage and dictionary encoding compress this footprint substantially. The numbers above are conservative.

### Partitioning Strategy

The `snapshots` table is logically partitioned by date and platform via the storage layout:

```text
~/.augur/data/
├── augur.duckdb                     # hot tables: signals, manipulation_flags,
│                                    #             calibration_fpr, reliability_curves,
│                                    #             signal_labels, recent snapshots
└── snapshots_archive/
    ├── platform=polymarket/
    │   ├── date=2026-04-14/snapshots.parquet
    │   ├── date=2026-04-15/snapshots.parquet
    │   └── ...
    └── platform=kalshi/
        ├── date=2026-04-14/snapshots.parquet
        └── ...
```

Snapshots older than 7 days are exported to the Parquet archive nightly and dropped from the hot DuckDB table. DuckDB's external Parquet scanning handles backtest queries against the archive transparently.

The `signals`, `manipulation_flags`, `calibration_fpr`, `reliability_curves`, and `signal_labels` tables stay entirely in the hot DuckDB file. They are small (millions of rows over years) and benefit from in-database indexing.

### Backtesting Read Isolation

DuckDB serializes writes through a single connection. A long-running backtest query can block live snapshot inserts. To avoid this:

1. **Backtest queries run against the Parquet archive,** not the hot DuckDB table. The archive is read-only and supports concurrent scanning.
2. **The hot DuckDB connection is reserved for the live engine.** A separate process (the backtest harness) opens its own DuckDB connection in read-only mode against the same file when archive data is insufficient.
3. **Backfill jobs (e.g., relabeling, recalibration) run during the nightly maintenance window** when polling is at the 300 s tier and write contention is minimal.

These rules avoid the original design's contention issue without changing the embedded-DuckDB architecture.

## Migration Trigger

The migration from embedded DuckDB to multi-process TimescaleDB is triggered by either of:

| Trigger                       | Threshold                                              | Source of Truth                  |
| ----------------------------- | ------------------------------------------------------ | -------------------------------- |
| Hot snapshot table size       | > 80 million rows                                      | `SELECT COUNT(*) FROM snapshots` |
| P95 backtest query latency    | > 30 seconds for queries scanning > 30 days of archive | Backtest harness telemetry       |
| P99 live ingest write latency | > 500 ms                                               | Engine telemetry                 |

The first trigger fires earliest in the natural growth path (≈ 9 months at 100 markets, 30 s cadence). The other two are guards against degradation.

When any trigger fires, the migration begins. The engine continues operating on DuckDB during the migration; the cutover is staged.

## Phase 5 Storage — TimescaleDB and Multi-Process

The post-migration architecture decomposes into:

| Process                                 | Role                                                                               |
| --------------------------------------- | ---------------------------------------------------------------------------------- |
| Polling workers (one per platform)      | Fetch market data, push to message bus                                             |
| Feature workers                         | Consume snapshots from bus, compute features, push to bus                          |
| Detector workers                        | Consume features, run detectors, push raw signals to bus                           |
| Manipulation worker                     | Consume raw signals, attach flags, push to bus                                     |
| Calibration worker                      | Consume flagged signals, attach confidence, push to bus                            |
| Dedup worker                            | Consume calibrated signals, merge per `./deduplication-and-storms.md`, push to bus |
| Context assembly workers                | Consume merged signals, build context, push to bus                                 |
| Formatter workers (one per output type) | Consume context, format, deliver                                                   |

The message bus is either NATS or Redis Streams. Choice is deferred to the phase spec; both are compatible with the schema.

TimescaleDB hypertables replace the DuckDB tables. Time-based partitioning is automatic. Read replicas serve backtests without contending with live writes. The same SQL schema as Phase 1 applies, with TimescaleDB-specific `CREATE_HYPERTABLE` calls added.

## Data Migration Procedure

1. **Stand up TimescaleDB** in parallel with the running DuckDB engine. Replicate the schema.
2. **Backfill historical data** from the Parquet archive into TimescaleDB hypertables. Use `pg_partman` for partition management. This is a one-time bulk load.
3. **Dual-write window.** The DuckDB engine continues to write to DuckDB; a sidecar process tails new DuckDB inserts and replays them into TimescaleDB. The dual-write window is at least 7 days.
4. **Cutover.** Switch the engine's storage backend to TimescaleDB. Verify schema compliance, run a backtest against TimescaleDB to confirm parity with the prior DuckDB results.
5. **Decommission.** Keep the DuckDB file as a read-only fallback for at least 30 days, then archive.

The migration is reversible until the decommission step.

## Cost Estimates

### Phase 1 (Embedded, Single Machine)

| Resource                                           | Estimate                                                  |
| -------------------------------------------------- | --------------------------------------------------------- |
| Compute                                            | One M1 Pro or equivalent (≤ $50/month amortized hardware) |
| Storage (hot DuckDB)                               | < 5 GB                                                    |
| Storage (Parquet archive, year 1)                  | < 12 GB                                                   |
| Storage (Parquet archive, year 3)                  | < 40 GB                                                   |
| LLM inference (Phase 4, opt-in, local Gemma class) | $0 marginal cost                                          |
| LLM inference (Phase 4, opt-in, cloud fallback)    | Variable; estimated < $20/month at MVP signal volume      |

### Phase 5 (Multi-Process, TimescaleDB)

| Resource                            | Estimate                                                             |
| ----------------------------------- | -------------------------------------------------------------------- |
| Compute (workers)                   | 4 to 8 cores across worker pool                                      |
| TimescaleDB                         | Managed service ≈ $100 to $300/month for the size band Augur reaches |
| Message bus (managed NATS or Redis) | $50 to $150/month                                                    |
| Object storage (cold archive)       | < $5/month for Parquet beyond TimescaleDB retention                  |

These estimates are order-of-magnitude. The exact numbers depend on whether managed services or self-hosted infrastructure is chosen and on whether the optional LLM formatter runs at scale.

## Retention Policy

| Data                  | Retention                                              |
| --------------------- | ------------------------------------------------------ |
| `snapshots` (hot)     | 7 days, then exported to Parquet archive               |
| `snapshots` (archive) | Indefinite, subject to disk capacity                   |
| `features`            | 30 days, then dropped (recomputable from snapshots)    |
| `signals`             | Indefinite                                             |
| `manipulation_flags`  | Indefinite, joined with `signals`                      |
| `calibration_fpr`     | 1 year of nightly snapshots, then monthly summaries    |
| `reliability_curves`  | All curve versions retained for replay reproducibility |
| `signal_labels`       | Indefinite, paired with the labeled corpus             |

Long-horizon trend analysis requires retention of the underlying snapshots. The Parquet archive is the system of record for that purpose.

## Failure Modes

| Failure                                     | Impact                        | Mitigation                                                                 |
| ------------------------------------------- | ----------------------------- | -------------------------------------------------------------------------- |
| DuckDB file corruption                      | Hot data loss; archive intact | Nightly backup of hot file; rebuild from archive plus backup               |
| Disk full                                   | Engine halts on next write    | Disk capacity alert at 80%; archive export at 70%                          |
| TimescaleDB connection exhaustion (Phase 5) | Worker stalls                 | Connection pool with max-in-flight; circuit breaker per worker             |
| Message bus partition (Phase 5)             | Event loss in worst case      | At-least-once delivery semantics; idempotent consumers; dedup on signal_id |

The Phase 1 architecture's primary failure mode is single-machine outage. This is acceptable for the MVP's scope but is the motivation for the Phase 5 multi-process decomposition.
