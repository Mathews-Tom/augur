# Deduplication and Storm Handling

This document specifies the algorithm by which raw signals from the detector layer are merged into the canonical signal stream, and how the system behaves under signal storms — periods when many detectors fire many signals across many correlated markets in a short window. The original design's "deduplicate + merge co-occurring signals" is expanded here into a concrete merge protocol with a storm-mode fallback.

## Why Dedup Matters

Five detectors run independently against the feature pipeline. A single underlying event — a Federal Reserve announcement, a geopolitical incident, a major regulatory action — typically triggers:

- Multiple detectors on the same market (price velocity + volume spike).
- The same detector on multiple correlated markets (price velocity on every macro contract in a Fed-policy cluster).
- Cross-market divergence detectors firing on every related-market pair where one side moved faster than the other.

Without dedup, a single Fed announcement can produce 30+ raw signals in 60 seconds. The downstream context assembler and formatters cannot keep pace, the LLM formatter (when enabled) backs up under load, and consumers receive a flood of redundant briefs that degrade signal-to-noise.

Dedup compresses this stream while preserving the information value. The output of the dedup layer is the canonical signal stream that reaches the bus.

## Signal Fingerprint

The first dedup step is exact-fingerprint deduplication. Two raw signals are duplicates if they share:

```
fingerprint = (market_id, signal_type, time_bucket(detected_at, 30 seconds))
```

`time_bucket(t, n)` rounds `t` down to the nearest `n`-second boundary. Two signals on the same market, of the same type, within the same 30-second bucket are merged into one.

When merging, the merged signal takes:

- The maximum `magnitude` of the inputs.
- The maximum `confidence` of the inputs.
- The union of `manipulation_flags`.
- The union of `related_market_ids`.
- The earliest `detected_at` timestamp.
- A composite `signal_id` (the smallest of the input signal_ids by lexicographic order).
- A merge-provenance entry in `raw_features` listing the source signal_ids.

Same-fingerprint dedup typically removes 30 to 60 percent of raw signal volume during normal operation.

## Cluster-Level Merge

The second dedup step uses the curated taxonomy. Signals on different markets that share a taxonomy edge of type `positive`, `inverse`, or `causal` are candidates for cluster-level merge if they fire within a 90-second window and share the same `signal_type`.

Cluster merge produces a single signal per cluster per 90-second window with:

- `market_id` set to the highest-liquidity-tier market in the cluster (ties broken by alphabetic market_id).
- `related_market_ids` populated with every other market in the cluster.
- `magnitude` and `confidence` are the max across cluster members.
- `manipulation_flags` is the union across cluster members; the result is conservative.
- `raw_features["cluster_member_signal_ids"]` lists every source signal_id.

Cluster-level merge typically removes another 20 to 40 percent of post-fingerprint signal volume during correlated events.

`complex` and unknown taxonomy edges do not trigger cluster merge — only the strong relationship types (`positive`, `inverse`, `causal`) are considered, because cluster merge implicitly asserts that the clustered signals share a cause.

## Queue Bounds

The dedup layer is the only producer feeding the signal bus. The bus has a bounded async queue:

| Parameter                                | Value                 |
| ---------------------------------------- | --------------------- |
| Bus queue capacity                       | 256 signals           |
| Per-consumer subscriber buffer           | 64 signals            |
| Context assembler concurrency            | 4 workers             |
| LLM formatter concurrency (when enabled) | 1 worker (sequential) |

These bounds are configurable. The defaults are chosen so that a normal-volume day stays well below capacity.

## Storm Detection

A signal storm is detected when either:

- Raw signal arrival rate (pre-dedup) exceeds 20 signals per second sustained for 30 seconds, OR
- Bus queue depth exceeds 75% of capacity (192 of 256) sustained for 10 seconds.

When either trigger fires, the system enters storm mode. A `StormStartEvent` is emitted to the operations channel.

## Storm-Mode Behavior

In storm mode, three behaviors change:

### 1. Cluster-Only Output

Single-market signals (signals not part of any taxonomy cluster) are dropped. Only cluster-level merged signals reach the bus. This is conservative — the consumer loses the per-market detail but retains the cluster-level event. Investigation prompts in the resulting `SignalContext` direct the consumer to check the related markets explicitly.

### 2. LIFO Drop Policy

If the bus queue is full when a new signal arrives, the dedup layer drops the _oldest_ signal in the bus queue and inserts the new one at the head. The reasoning: in a storm, the most recent signal is usually the most informative because it reflects the latest state of the market. Dropping older signals prioritizes timeliness over completeness.

Dropped signals are logged with their signal*ids so backtests can compare the dropped set against the labeled corpus. Storm-mode drops are a known accuracy cost; the alternative — unbounded queue growth or dropped \_new* signals — is worse.

### 3. LLM Formatter Suspended

The optional LLM formatter (when enabled) is suspended in storm mode. Briefs route only through the deterministic JSON and Markdown formatters. The LLM formatter is the slowest stage in the pipeline (5 to 10 seconds per brief on a local model); leaving it active during a storm guarantees downstream backpressure.

When storm mode ends, the LLM formatter resumes. Signals that arrived during storm mode are not retroactively formatted by the LLM — only signals arriving after `StormEndEvent` are eligible.

## Storm Recovery

The system exits storm mode when both:

- Raw signal arrival rate drops below 5 signals per second sustained for 60 seconds, AND
- Bus queue depth drops below 25% of capacity sustained for 30 seconds.

A `StormEndEvent` is emitted. The system reverts to normal dedup behavior and the LLM formatter resumes.

## Worked Example

A Federal Reserve rate decision at 14:00 UTC produces:

| Time     | Event                                                                                          |
| -------- | ---------------------------------------------------------------------------------------------- |
| 14:00:01 | Fed announcement posts to Reuters                                                              |
| 14:00:05 | First trader reactions hit Polymarket and Kalshi macro markets                                 |
| 14:00:15 | Detector layer fires 12 signals across 8 macro markets (price velocity + volume spike on each) |
| 14:00:30 | Detector layer fires 6 more signals (cross-market divergence on Fed-rate vs Fed-holds pairs)   |
| 14:00:45 | Detector layer fires 4 more signals (regime shift on previously-dormant inflation markets)     |

Without dedup: 22 signals in 45 seconds, all reaching the bus, all generating briefs, all routing to consumers. The LLM formatter (if enabled) takes 3 to 4 minutes to clear the backlog.

With dedup:

1. Fingerprint dedup compresses same-bucket same-type signals: 22 raw → ≈ 14 signals.
2. Cluster merge groups signals by taxonomy: 14 → ≈ 4 cluster-level signals (one per Fed-policy sub-cluster: rates, inflation, employment, holds).
3. The bus receives 4 signals over 60 seconds. The context assembler processes them in parallel. Consumers receive 4 high-information briefs covering the full event.

Storm mode does not trigger because the rate is well within bounds. If the same event coincided with a separate geopolitical event firing 30+ additional signals on geopolitics markets, storm mode would activate, the LLM formatter would suspend, and only cluster-level signals would reach the bus.

## Configuration

```toml
[dedup]
fingerprint_bucket_seconds = 30
cluster_window_seconds = 90
cluster_relationship_types = ["positive", "inverse", "causal"]

[dedup.bus]
queue_capacity = 256
per_consumer_buffer = 64
context_assembler_concurrency = 4
llm_formatter_concurrency = 1

[dedup.storm]
trigger_signal_rate_per_sec = 20
trigger_signal_rate_window_sec = 30
trigger_queue_depth_pct = 0.75
trigger_queue_depth_window_sec = 10
recovery_signal_rate_per_sec = 5
recovery_signal_rate_window_sec = 60
recovery_queue_depth_pct = 0.25
recovery_queue_depth_window_sec = 30
```

## Failure Modes

| Failure                                       | Symptom                                          | Mitigation                                                                                                                                                                                                        |
| --------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dedup layer crashes                           | All raw signals fan out to the bus unmerged      | Engine watchdog restarts dedup; bus queue overflow protection limits damage                                                                                                                                       |
| Storm trigger oscillates                      | Repeated `StormStartEvent` / `StormEndEvent`     | Hysteresis: trigger and recovery thresholds are intentionally different                                                                                                                                           |
| Cluster merge collapses informative variation | Consumers lose per-market detail under storms    | Investigation prompts in the cluster-level brief direct consumers to inspect related-market state explicitly; raw signals are persisted to the `signals` table for post-hoc review even when dropped from the bus |
| LIFO drops a critical signal during storm     | Consumer never sees a particular market's signal | Acknowledged accuracy cost; backtests measure the rate; mitigated only by raising queue capacity and adding consumer concurrency, both of which have cost                                                         |

The design accepts that storms reduce per-signal fidelity in exchange for system-level stability. The alternative — unbounded queues that eventually exhaust memory — is worse.
