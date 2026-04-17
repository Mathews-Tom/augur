"""Append-only Parquet writer with per-partition file locking.

Events are partitioned by the date of ``ground_truth_timestamp``. Each
partition lives at ``<root>/date=YYYY-MM-DD/events.parquet``. The
writer acquires a filelock on the partition before every read-modify-
write so concurrent annotator processes do not corrupt the file.

Operational ceiling
-------------------
Each ``append`` re-reads the partition, concats, and rewrites under
the per-partition lock. For dense labeling days (dozens of events)
this is O(n²) I/O; the ceiling is several hundred events per day
before the 30 s default lock timeout becomes a bottleneck. Once the
corpus approaches that volume, migrate to a sibling-file layout
(``<partition>/events-<uuid>.parquet``) read via
``pq.ParquetDataset`` so each append writes only the new rows.
``supersede`` similarly scans every partition sequentially; an
``event_id -> partition_date`` index lets it jump directly to the
partition at scale.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock

from augur_labels.models import NewsworthyEvent
from augur_labels.storage._schema import NEWSWORTHY_EVENTS_SCHEMA


class AppendOnlyParquetWriter:
    """Concurrent-safe append-only writer for the labeled corpus."""

    def __init__(self, root: Path, lock_timeout_seconds: float = 30.0) -> None:
        self._root = root
        self._timeout = lock_timeout_seconds
        self._root.mkdir(parents=True, exist_ok=True)

    def _partition_dir(self, partition: date) -> Path:
        return self._root / f"date={partition.isoformat()}"

    def _partition_file(self, partition: date) -> Path:
        return self._partition_dir(partition) / "events.parquet"

    def _lock_path(self, partition: date) -> Path:
        return self._partition_dir(partition) / ".lock"

    def append(self, events: Sequence[NewsworthyEvent]) -> None:
        """Append *events* to their partitions, acquiring one lock per partition."""
        by_partition: dict[date, list[NewsworthyEvent]] = {}
        for event in events:
            key = event.ground_truth_timestamp.date()
            by_partition.setdefault(key, []).append(event)
        for partition, group in by_partition.items():
            self._append_partition(partition, group)

    def _append_partition(self, partition: date, events: Sequence[NewsworthyEvent]) -> None:
        partition_dir = self._partition_dir(partition)
        partition_dir.mkdir(parents=True, exist_ok=True)
        lock = FileLock(self._lock_path(partition), timeout=self._timeout)
        with lock:
            new_table = _to_table(events)
            target = self._partition_file(partition)
            if target.exists():
                existing = pq.read_table(target, schema=NEWSWORTHY_EVENTS_SCHEMA)
                combined = pa.concat_tables([existing, new_table])
            else:
                combined = new_table
            # Atomic replace via write-then-rename.
            staging = target.with_suffix(".parquet.tmp")
            pq.write_table(combined, staging)
            staging.replace(target)

    def supersede(self, event_id: str, replacement_id: str) -> None:
        """Mark an existing labeled event as superseded by *replacement_id*.

        Rewrites the partition containing *event_id* with the row's
        status updated and appends a note to corrects. The replacement
        event itself must already have been appended separately.
        """
        for partition_dir in sorted(self._root.glob("date=*")):
            target = partition_dir / "events.parquet"
            if not target.exists():
                continue
            lock = FileLock(partition_dir / ".lock", timeout=self._timeout)
            with lock:
                table = pq.read_table(target, schema=NEWSWORTHY_EVENTS_SCHEMA)
                event_ids = table.column("event_id").to_pylist()
                if event_id not in event_ids:
                    continue
                columns = {name: table.column(name).to_pylist() for name in table.schema.names}
                idx = event_ids.index(event_id)
                columns["status"][idx] = "superseded"
                columns["corrects"][idx] = replacement_id
                updated = pa.table(columns, schema=NEWSWORTHY_EVENTS_SCHEMA)
                staging = target.with_suffix(".parquet.tmp")
                pq.write_table(updated, staging)
                staging.replace(target)
                return
        raise KeyError(f"event_id={event_id!r} not found in labeled corpus")


def _to_table(events: Sequence[NewsworthyEvent]) -> pa.Table:
    columns: dict[str, list[object]] = {
        "event_id": [],
        "ground_truth_timestamp": [],
        "market_ids": [],
        "category": [],
        "headline": [],
        "source_urls": [],
        "source_publishers": [],
        "labeler_ids": [],
        "label_protocol_version": [],
        "corrects": [],
        "status": [],
        "created_at": [],
    }
    for event in events:
        columns["event_id"].append(event.event_id)
        columns["ground_truth_timestamp"].append(_to_utc(event.ground_truth_timestamp))
        columns["market_ids"].append(list(event.market_ids))
        columns["category"].append(event.category)
        columns["headline"].append(event.headline)
        columns["source_urls"].append(list(event.source_urls))
        columns["source_publishers"].append(list(event.source_publishers))
        columns["labeler_ids"].append(list(event.labeler_ids))
        columns["label_protocol_version"].append(event.label_protocol_version)
        columns["corrects"].append(event.corrects)
        columns["status"].append(event.status)
        columns["created_at"].append(_to_utc(event.created_at))
    return pa.table(columns, schema=NEWSWORTHY_EVENTS_SCHEMA)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must carry tzinfo")
    return value
