"""Dual-write sidecar replaying engine writes into TimescaleDB.

The sidecar subscribes to the engine's write-tee bus subject (a
dedicated `augur.writes.*` channel the engine fans off during the
dual-write window) and replays every snapshot, feature, and signal
into TimescaleDB alongside the primary DuckDB write. It maintains a
per-table lag counter and fails the Prometheus
`augur_dual_write_lag_seconds` gauge past the configured threshold.

Usage:

    uv run python scripts/dual_write_sidecar.py \\
        --lag-alert-seconds 10 --bus-backend redis

Rollback-friendly: if operators flip `storage.toml` back to DuckDB,
the sidecar observes no writes on the tee subject and sits idle until
the flag flips again. It never modifies DuckDB; it only reads the tee
and writes the mirror copy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from augur_signals._observability import MetricCounter, MetricGauge

if TYPE_CHECKING:
    from augur_signals.bus.base import BusMessage, EventBus
    from augur_signals.storage.timescaledb_store import TimescaleDBStore


class ClockReader(Protocol):
    """Inject a clock so tests drive lag computation deterministically."""

    def now(self) -> datetime: ...


@dataclass(slots=True)
class _WallClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


@dataclass(slots=True)
class LagTracker:
    """Maintains a per-table lag gauge and alerts above the threshold."""

    threshold_seconds: int
    gauge: MetricGauge
    alerts: MetricCounter
    clock: ClockReader = field(default_factory=_WallClock)

    def record(self, table: str, message_ts: datetime) -> float:
        delta = (self.clock.now() - message_ts).total_seconds()
        self.gauge.set(delta, table=table)
        if delta > self.threshold_seconds:
            self.alerts.inc(table=table)
        return delta


async def run_sidecar(
    *,
    bus: EventBus,
    tee_subject: str,
    consumer_group: str,
    store: TimescaleDBStore,
    tracker: LagTracker,
    stop_after: int | None = None,
) -> int:
    """Consume write-tee messages and replay into *store*.

    Args:
        bus: EventBus carrying the tee subject.
        tee_subject: Subject the engine fans write events to.
        consumer_group: Consumer-group name; stable across restarts so
            the sidecar resumes from the last acked entry.
        store: TimescaleDBStore mirror target.
        tracker: LagTracker recording observed lag per table.
        stop_after: Optional cap on processed events (test only). None
            keeps running until cancelled.

    Returns:
        Number of events replayed.
    """
    await bus.connect()
    processed = 0
    try:
        async for message in _subscribe(bus, tee_subject, consumer_group):
            payload = json.loads(message.payload)
            table = str(payload["table"])
            event_time = datetime.fromisoformat(payload["ts"])
            tracker.record(table, event_time)
            await _apply(store, table, payload["row"])
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
    finally:
        await bus.close()
    return processed


def _subscribe(bus: EventBus, subject: str, group: str) -> AsyncIterator[BusMessage]:
    """Thin indirection so tests can swap the subscription source."""
    return bus.subscribe(subject, group)


async def _apply(store: TimescaleDBStore, table: str, row: dict[str, object]) -> None:
    """Dispatch the tee event to the matching TimescaleDBStore write."""
    from augur_signals.models import FeatureVector, MarketSignal, MarketSnapshot

    if table == "snapshots":
        await store.insert_snapshot(MarketSnapshot.model_validate(row))
    elif table == "features":
        await store.insert_feature(FeatureVector.model_validate(row))
    elif table == "signals":
        await store.insert_signal(MarketSignal.model_validate(row))
    else:
        raise ValueError(f"Unknown tee table: {table!r}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dual_write_sidecar")
    parser.add_argument("--lag-alert-seconds", type=int, default=10)
    parser.add_argument("--bus-backend", choices=["nats", "redis"], default="nats")
    parser.add_argument("--tee-subject", default="augur.writes")
    parser.add_argument("--consumer-group", default="dual_write")
    return parser.parse_args(argv)


async def _cli(argv: list[str]) -> int:  # pragma: no cover — entrypoint only
    args = _parse_args(argv)
    from pathlib import Path

    from augur_signals._config import load_config
    from augur_signals.bus._config import BusConfig
    from augur_signals.bus.factory import make_event_bus
    from augur_signals.storage._config import StorageConfig
    from augur_signals.storage.factory import make_timescaledb_store

    bus_cfg = load_config(Path("config/bus.toml"), BusConfig)
    store_cfg = load_config(Path("config/storage.toml"), StorageConfig)
    bus = make_event_bus(bus_cfg)
    store = await make_timescaledb_store(store_cfg)
    tracker = LagTracker(
        threshold_seconds=args.lag_alert_seconds,
        gauge=MetricGauge("augur_dual_write_lag_seconds", ["table"]),
        alerts=MetricCounter("augur_dual_write_lag_alerts_total", ["table"]),
    )
    processed = await run_sidecar(
        bus=bus,
        tee_subject=args.tee_subject,
        consumer_group=args.consumer_group,
        store=store,
        tracker=tracker,
    )
    print(f"replayed {processed} events")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(_cli(sys.argv[1:])))
