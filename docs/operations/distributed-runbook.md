# Distributed Runtime Operational Runbook

The Phase 5 multi-process deployment is triggered by growth thresholds in `.docs/phase-5-scaling.md §2`: >80M snapshot rows, P95 backtest latency >30s, or P99 live-write latency >500ms, each observed twice across separate measurement windows. Until the triggers fire, the single-process engine is the supported deployment.

This runbook covers cutover, rollback, failover response, and on-call escalation for the distributed runtime.

## 1. Pre-Cutover Checklist

| Item | How to verify |
| --- | --- |
| TimescaleDB primary provisioned with hypertables | `SELECT * FROM timescaledb_information.hypertables` returns rows for `snapshots`, `features`, `signals` |
| Backfill complete with row-count parity | `scripts/migrate_to_timescale.py verify --start ... --end ...` exits 0 |
| Dual-write sidecar lag <10s for ≥7 days | `augur_dual_write_lag_seconds{table=*}` max-over-time stays under threshold |
| NATS or Redis bus operational; consumer groups created | `augur_bus_consume_lag_seconds` reports a value per `(topic, consumer_group)` |
| Shadow workers running for ≥48h without errors | `augur_worker_alive{worker_kind=*} == 1` continuously |
| Distributed lock backend seeded | `SET augur.lock.dedup ...` responds OK; NATS KV bucket exists |

## 2. Cutover Procedure

1. Announce the freeze window on the ops channel; set the monolith engine to drain mode (`AUGUR_DRAIN=true` env var) and let it finish in-flight cycles.
2. Flip `config/storage.toml`:

    ```toml
    [backend]
    kind = "timescaledb"          # was "duckdb"
    ```

3. Apply the updated ConfigMap: `kubectl apply -k ops/deploy/`.
4. Restart the monolith engine (or run `kubectl rollout restart deployment/augur-engine`) — the new process picks up TimescaleDB at startup and opens a connection pool from `AUGUR_TIMESCALE_URL`.
5. Watch `augur_db_query_seconds{table, operation}` for 15 minutes; rollback if P95 exceeds the pre-cutover DuckDB baseline by 2×.
6. Bring workers online in the order recommended in `.docs/phase-5-scaling.md §12.1`: manipulation → feature → detector → calibration → context_format → dedup → LLM.

## 3. Rollback Procedure

Rollback is always available for 30 days post-cutover because the Parquet archive is preserved.

1. Flip `config/storage.toml` `backend.kind` back to `"duckdb"` and reapply the ConfigMap.
2. Scale the workers to zero: `kubectl scale --replicas=0 -n augur deployment --all statefulset --all`.
3. Start the monolith engine against the DuckDB archive.
4. Announce rollback on the ops channel and file a post-incident ticket with the TimescaleDB query traces that motivated rollback.

After the DuckDB path is removed (day 30+), rollback requires restoring from a TimescaleDB backup — see §5.

## 4. Failover Response

### 4.1 Dedup Singleton

Symptom: `augur_singleton_lock_holder{singleton_kind="dedup"}` drops to 0, or `augur_failover_total{singleton_kind="dedup"}` increments.

Procedure:

1. Confirm the active pod was terminated: `kubectl get pod -n augur -l app.kubernetes.io/component=dedup`.
2. Observe the passive replica acquire the lock within `lock.ttl_seconds + renew_interval_seconds` (default 40s). The metric flips back to 1 with the new pod name.
3. If the lock stays unheld for >2× `ttl_seconds`, manually delete the stale lock:
    - Redis: `redis-cli DEL augur.lock.dedup`
    - NATS: `nats kv delete augur-locks dedup`
4. Force a restart of both replicas so the acquire race runs clean: `kubectl rollout restart -n augur statefulset/augur-dedup`.

### 4.2 LLM Formatter

Identical to dedup with `singleton_kind="llm_formatter"`. In-flight briefs at failover time are dropped — by design per Phase 4 guidance. No retry.

### 4.3 Stateful Worker (feature / detector)

Stateful workers persist their per-market cursor to TimescaleDB every 60 seconds. On crash:

1. Kubernetes reschedules the pod; the replacement replica reads the last persisted cursor and resumes.
2. If the shard count changed (HPA scaled the deployment), the new owner replays from the last cursor of the displaced replica. Expect a short backlog as messages re-ack.
3. Monitor `augur_bus_consume_lag_seconds{topic="augur.features.*", consumer_group="feature-*"}` — it should return below 5s within one poll cycle.

## 5. Backup and Restore

| Artefact | Cadence | Retention |
| --- | --- | --- |
| TimescaleDB base backup | Daily (pg_basebackup) | 30 days |
| TimescaleDB WAL | Continuous archive to S3-equivalent | 14 days |
| Parquet archive | Written by engine during dual-write | 30 days post-cutover, then 1 year cold |
| Reliability curves | Checkpointed per calibration run | Indefinite |

Restore: `pg_basebackup` into a replacement host, replay WAL to the desired point-in-time, rerun `TimescaleDBStore.initialize` to validate hypertable definitions, then swap `AUGUR_TIMESCALE_URL`.

## 6. SLO Response Thresholds

| SLO | Target | Page if |
| --- | --- | --- |
| End-to-end signal latency P95 | <60s | >60s for 5+ min |
| End-to-end signal latency P99 | <120s | >120s for 5+ min |
| Live ingest write P99 | <200ms | >200ms for 2+ min |
| Bus consume lag P95 | <5s | >5s for 5+ min |
| Dedup failover time | <60s | >60s observed |
| LLM brief rejection rate | <5% / hr | >5% for 1 hr |

Pager rotation and escalation are operations-team-owned; the engineering runbook only defines the thresholds.

## 7. Common Investigations

- **High bus lag on one shard**: check `augur_worker_processed_total{worker_kind="feature", replica_id="..."}` per replica. A replica that plateaus while peers advance is likely stuck on a long-running transform.
- **Increasing LLM rejections**: inspect `augur_llm_briefs_rejected_total{reason}` — the label identifies the gate that dropped the brief (forbidden token, schema violation, consumer gate, backend error).
- **TimescaleDB lock contention**: correlate `augur_db_query_seconds{operation="write"}` tail with pg_stat_activity; a handful of long-held WAL-sender sessions usually point to a slow read replica.
