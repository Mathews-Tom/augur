"""Poller worker entrypoint — one per platform.

The poller subscribes to the platform's public market API via the
Phase 1 ``AdaptivePoller`` and forwards every normalized snapshot to
``augur.snapshots.<platform>.<market_id>`` on the event bus.

Run as:
    python -m augur_signals.workers.poller --platform polymarket

The main coroutine stays thin — it wires the harness to the existing
Phase 1 polling stack. The heavy lifting (adaptive backoff, rate
limiting, DLQ, manipulation hints) already lives in
``augur_signals.ingestion``; this module only glues it to the bus.
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator, Callable
from typing import Protocol

from augur_signals._observability import trace_span
from augur_signals.bus.base import BusMessage, EventBus
from augur_signals.models import MarketSnapshot
from augur_signals.workers.harness import WorkerHarness
from augur_signals.workers.subjects import snapshots


class SnapshotSource(Protocol):
    """Abstract snapshot producer for the poller worker.

    Phase 1's ``AdaptivePoller`` implements this; tests pass a simple
    stub. The poller does not own market discovery — that lives in
    ``augur_signals.ingestion``.
    """

    def stream(self) -> AsyncIterator[MarketSnapshot]: ...


async def run_poller(harness: WorkerHarness, source: SnapshotSource, subject_prefix: str) -> None:
    """Publish each snapshot from *source* to its shard-routed subject."""
    async for snapshot in source.stream():
        if harness.should_stop():
            break
        subject = snapshots(subject_prefix, snapshot.platform, snapshot.market_id)
        payload = snapshot.model_dump_json().encode("utf-8")
        with trace_span(
            "poller.publish",
            market_id=snapshot.market_id,
            platform=snapshot.platform,
        ):
            await harness.bus.publish(BusMessage(subject=subject, payload=payload))
        harness.record_processed()


def build_harness(
    *,
    platform: str,
    replica_id: str,
    bus: EventBus,
    source: SnapshotSource,
    subject_prefix: str,
) -> WorkerHarness:
    """Assemble a ``WorkerHarness`` around ``run_poller`` for *platform*."""

    async def _main(harness: WorkerHarness) -> None:
        await run_poller(harness, source, subject_prefix)

    return WorkerHarness(
        worker_kind=f"poller.{platform}",
        replica_id=replica_id,
        bus=bus,
        main=_main,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="augur-poller")
    parser.add_argument("--platform", required=True, choices=["polymarket", "kalshi"])
    parser.add_argument("--replica-id", required=True)
    parser.add_argument("--subject-prefix", default="augur")
    return parser.parse_args(argv)


def main_factory_for(
    platform: str,
) -> Callable[[EventBus, SnapshotSource, str, str], WorkerHarness]:
    """Curry ``build_harness`` for a given platform.

    Entrypoint scripts under ``python -m augur_signals.workers.poller``
    call this after parsing args; full container startup wires in the
    concrete ``SnapshotSource`` from ``augur_signals.ingestion``.
    """

    def _build(
        bus: EventBus, source: SnapshotSource, replica_id: str, subject_prefix: str
    ) -> WorkerHarness:
        return build_harness(
            platform=platform,
            replica_id=replica_id,
            bus=bus,
            source=source,
            subject_prefix=subject_prefix,
        )

    return _build


if __name__ == "__main__":  # pragma: no cover — thin entrypoint wiring
    _parse_args()
    raise SystemExit(
        "augur-poller requires a SnapshotSource wired from "
        "augur_signals.ingestion at deployment time. Import build_harness "
        "from your deployment's bootstrap module."
    )
