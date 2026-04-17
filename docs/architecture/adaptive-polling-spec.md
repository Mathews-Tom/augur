# Adaptive Polling Specification

This document specifies the polling-rate state machine used by the ingestion layer. The original design described adaptive polling as a flowchart with no hysteresis and no platform rate-limit accounting; this specification closes both gaps.

## Polling Tiers

The ingestion layer assigns each tracked market to one of four polling tiers:

| Tier   | Interval    | Intended For                                                                             |
| ------ | ----------- | ---------------------------------------------------------------------------------------- |
| `hot`  | 15 seconds  | Markets with elevated current activity (active signals, surging volume, near-resolution) |
| `warm` | 30 seconds  | Default tier for high-liquidity markets in normal activity                               |
| `cool` | 60 seconds  | Mid-liquidity markets and high-liquidity markets in low-activity windows                 |
| `cold` | 300 seconds | Low-liquidity markets and high-liquidity markets in dormant periods                      |

The interval applies to snapshot polling. Order-book polling shares the same interval. Trade polling runs at the snapshot interval but with a 1-tier delay (orders settle before trades appear).

## Tier Transition Triggers

Tier transitions are evaluated at every polling tick. Triggers compare against the per-market state computed in the feature pipeline.

### Promotion (cooler → hotter)

| Current Tier | Trigger to Promote                                                      | Target Tier |
| ------------ | ----------------------------------------------------------------------- | ----------- |
| `cold`       | Volume ratio (1 h window) > 1.1 × baseline                              | `cool`      |
| `cool`       | Volume ratio (1 h window) > 1.5 × baseline OR market closes within 24 h | `warm`      |
| `warm`       | Volume ratio (1 h window) > 2.2 × baseline OR active signal in last 4 h | `hot`       |

### Demotion (hotter → cooler)

| Current Tier | Trigger to Demote                                                                | Target Tier |
| ------------ | -------------------------------------------------------------------------------- | ----------- |
| `hot`        | Volume ratio (1 h window) < 1.8 × baseline AND no active signal in last 4 h      | `warm`      |
| `warm`       | Volume ratio (1 h window) < 1.3 × baseline AND market closes more than 24 h away | `cool`      |
| `cool`       | Volume ratio (1 h window) < 0.9 × baseline                                       | `cold`      |

## Hysteresis Bands

Promotion and demotion thresholds are intentionally asymmetric. The gap between the promotion threshold and the demotion threshold is the hysteresis band, computed as ±10% around the nominal switch point:

| Tier Boundary   | Promote At         | Demote At          | Band Width          |
| --------------- | ------------------ | ------------------ | ------------------- |
| `cold` ↔ `cool` | volume_ratio > 1.1 | volume_ratio < 0.9 | 0.2 (≈ ±10% of 1.0) |
| `cool` ↔ `warm` | volume_ratio > 1.5 | volume_ratio < 1.3 | 0.2 (≈ ±7% of 1.4)  |
| `warm` ↔ `hot`  | volume_ratio > 2.2 | volume_ratio < 1.8 | 0.4 (≈ ±10% of 2.0) |

The band ensures that a market sitting near a threshold does not flap between tiers on consecutive ticks. Without the band, polling rate would oscillate at the polling cadence itself, which would corrupt rolling-window features whose semantics depend on consistent temporal sampling.

A tier transition takes effect on the next tick after the trigger evaluates true. There is no transition delay beyond one tick.

## Wall-Clock vs Observation-Count Window Reconciliation

Detectors operate on rolling windows expressed in seconds (5 m, 15 m, 1 h, 4 h). When a market changes polling tier, the number of observations within a fixed-second window changes. Two reconciliation rules apply:

1. **Window definitions are observation-count internally.** The `5m` window is implemented as `floor(window_seconds / current_polling_interval)` observations, recomputed each tick. The window holds the most recent N observations regardless of how long they span.
2. **Wall-clock window labels are kept for human-readable reporting only.** A `volatility_5m` value computed during a `cold`-tier (300 s) period actually spans up to 25 minutes of wall clock. This is acceptable because the feature pipeline is computing the volatility _of the available samples_, not of an unobserved continuous process.

For backtests, the polling interval at each historical observation is recorded with the snapshot, so window computations during replay match the original computations exactly.

## Rate-Limit Budget

Both Polymarket and Kalshi enforce per-IP and per-API-key rate limits. The polling scheduler computes a budget at startup and rebalances per minute.

### Per-Platform Caps (As of Documentation Date)

| Platform   | Limit                                                  | Source                                  |
| ---------- | ------------------------------------------------------ | --------------------------------------- |
| Polymarket | ≈ 600 requests / minute / IP for public REST endpoints | Public documentation; subject to change |
| Kalshi     | ≈ 1000 requests / minute / API key                     | Public documentation; subject to change |

Each polling tick on a market consumes 2 to 3 requests (snapshot + orderbook + occasional trades). With 100 markets:

| Tier Allocation              | Requests per Minute       |
| ---------------------------- | ------------------------- |
| 10 markets at `hot` (15 s)   | 10 × 4 × 2.5 = 100        |
| 30 markets at `warm` (30 s)  | 30 × 2 × 2.5 = 150        |
| 30 markets at `cool` (60 s)  | 30 × 1 × 2.5 = 75         |
| 30 markets at `cold` (300 s) | 30 × 0.2 × 2.5 = 15       |
| **Total**                    | **340 requests / minute** |

Distributed across both platforms with rough proportional split (60% Polymarket, 40% Kalshi):

| Platform   | Requests / Minute | Cap  | Headroom |
| ---------- | ----------------- | ---- | -------- |
| Polymarket | 204               | 600  | 66%      |
| Kalshi     | 136               | 1000 | 86%      |

This budget is sustainable. The scheduler additionally caps total requests per minute per platform to 70% of the published limit to leave headroom for retries and unanticipated bursts.

### Budget Rebalancing

If the engine approaches the per-platform cap (≥ 80% utilization), the scheduler:

1. Demotes the lowest-priority `hot` markets to `warm` until utilization drops below 70%.
2. Logs a `RateLimitPressureEvent` for operations review.
3. If demotion does not relieve pressure, drops `cold`-tier polling to 600 s as a final guard.

The scheduler never exceeds the published rate limit. Soft-limit breaches that the platform tolerates (some platforms allow short bursts above the published rate) are not exploited.

## Backoff Policy

When a request fails with a rate-limit response or a 5xx error:

1. **Exponential backoff** starting at 1 s, doubling per attempt, capped at 60 s.
2. **Maximum 5 retries** per request.
3. **After 5 failures**, the polling tick is skipped and the next tick proceeds normally.
4. **Skipped ticks are recorded** in the feature pipeline as gaps; the EWMA decay correction described in `./system-design.md` handles the gap.

A market that fails 10 consecutive ticks is demoted to `cold` regardless of trigger conditions. A market that fails 50 consecutive ticks is removed from the active watchlist and reported via the `MarketUnreachableEvent`.

## Failure Modes

| Failure                                            | Symptom                               | Engine Behavior                                                                                     |
| -------------------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Platform API outage                                | All requests to platform fail         | Backoff per request; mark all platform markets as `cold`; alert                                     |
| Single market disappears (delisted)                | Repeated 404s                         | Remove from watchlist; emit `MarketDelistedEvent`                                                   |
| Rate limit exceeded mid-cycle                      | 429 responses                         | Backoff per request; demote markets per rebalancing rule                                            |
| Polling-rate flap (would occur without hysteresis) | Tier transitions on alternating ticks | Prevented by hysteresis bands above                                                                 |
| Clock skew between engine and platform             | Snapshot timestamps drift             | Engine uses platform-reported timestamp where available; otherwise local UTC; logged on > 5 s drift |

## Configuration

```toml
[polling]
hot_interval_s = 15
warm_interval_s = 30
cool_interval_s = 60
cold_interval_s = 300

[polling.hysteresis]
hot_promote = 2.2
hot_demote = 1.8
warm_promote = 1.5
warm_demote = 1.3
cool_promote = 1.1
cool_demote = 0.9

[polling.platform_caps]
polymarket_per_min = 600
kalshi_per_min = 1000
budget_safety_pct = 0.7

[polling.backoff]
initial_s = 1
max_s = 60
max_retries = 5
demote_after_consecutive_failures = 10
remove_after_consecutive_failures = 50
```

The configuration is human-readable and can be tuned operationally. Defaults reflect the design above.
