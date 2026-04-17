"""Stateless worker builders: feature, detector, manipulation, calibration, context_format.

Each of these workers consumes from one subject, runs a pure function
against the message payload, and publishes the output to another
subject. They share the ``run_bridge`` supervisor so the per-kind
entrypoints stay tiny: they supply a deserializer, a transform, a
serializer, and the input/output subjects.

The monolith's heavy pipeline logic (feature computation, detector
dispatch, manipulation flags, calibration) remains the single source
of truth. Phase 5 workers call into that logic rather than
reimplementing it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from augur_signals._observability import trace_span
from augur_signals.bus.base import BusMessage, EventBus
from augur_signals.workers.harness import WorkerHarness
from augur_signals.workers.sharding import owned_by


@dataclass(frozen=True, slots=True)
class ShardConfig:
    """Replica identity and pool size for per-market sharding."""

    replica_id: int
    replica_count: int


async def run_bridge[InT, OutT](
    harness: WorkerHarness,
    *,
    input_pattern: str,
    output_subject_builder: Callable[[OutT], str | None],
    consumer_group: str,
    deserialize: Callable[[bytes], InT],
    transform: Callable[[InT], Awaitable[list[OutT]]],
    serialize: Callable[[OutT], bytes],
    shard_key: Callable[[InT], str] | None = None,
    shard_config: ShardConfig | None = None,
    trace_name: str,
) -> None:
    """Consume *input_pattern*, transform each payload, publish outputs.

    Args:
        harness: The owning ``WorkerHarness``. Supplies the bus and
            stop signal.
        input_pattern: Subject pattern to subscribe to.
        output_subject_builder: Function returning the subject to
            publish each output to, or None to skip publishing (e.g.,
            for terminal workers that write to storage only).
        consumer_group: Consumer group name for the input subscription.
        deserialize: Parse the input payload from raw bytes.
        transform: Produce zero or more outputs from one input.
        serialize: Encode each output to bytes for publishing.
        shard_key: Optional extractor used with *shard_config* to skip
            messages this replica does not own.
        shard_config: Optional replica identity for shard filtering.
        trace_name: Name of the OpenTelemetry span wrapping each
            transform.
    """
    async for message in harness.bus.subscribe(input_pattern, consumer_group):
        if harness.should_stop():
            break
        deserialized = deserialize(message.payload)
        if shard_key is not None and shard_config is not None:
            key = shard_key(deserialized)
            if not owned_by(key, shard_config.replica_id, shard_config.replica_count):
                continue
        with trace_span(trace_name, replica_id=harness.replica_id):
            outputs = await transform(deserialized)
        for out in outputs:
            subject = output_subject_builder(out)
            if subject is None:
                continue
            await harness.bus.publish(BusMessage(subject=subject, payload=serialize(out)))
        harness.record_processed(float(max(len(outputs), 1)))


@dataclass(slots=True)
class StatelessWorkerSpec:
    """Declarative shape for a stateless worker.

    Construction is deferred until a bootstrap module has resolved the
    concrete transform function (which often depends on config loaded
    from disk).
    """

    worker_kind: str
    input_pattern: str
    consumer_group: str
    trace_name: str

    def build_harness(
        self,
        *,
        replica_id: str,
        bus: EventBus,
        deserialize: Callable[[bytes], object],
        transform: Callable[[object], Awaitable[list[object]]],
        serialize: Callable[[object], bytes],
        output_subject_builder: Callable[[object], str | None],
        shard_key: Callable[[object], str] | None = None,
        shard_config: ShardConfig | None = None,
    ) -> WorkerHarness:
        async def _main(harness: WorkerHarness) -> None:
            await run_bridge(
                harness,
                input_pattern=self.input_pattern,
                output_subject_builder=output_subject_builder,
                consumer_group=self.consumer_group,
                deserialize=deserialize,
                transform=transform,
                serialize=serialize,
                shard_key=shard_key,
                shard_config=shard_config,
                trace_name=self.trace_name,
            )

        return WorkerHarness(
            worker_kind=self.worker_kind,
            replica_id=replica_id,
            bus=bus,
            main=_main,
        )
