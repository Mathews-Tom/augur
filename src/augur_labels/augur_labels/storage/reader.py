"""Query API for the labeled corpus.

Calibration consumers (phase-1 EmpiricalFPR, ReliabilityAnalyzer) read
events through this API so the parquet layout and partition pruning
stay internal to the storage package.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from augur_labels.models import NewsworthyEvent
from augur_labels.storage._schema import NEWSWORTHY_EVENTS_SCHEMA


class LabelReader:
    """Read-only query surface over the append-only parquet partitions."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def events_in_window(
        self, start: datetime, end: datetime, status: str = "labeled"
    ) -> list[NewsworthyEvent]:
        events: list[NewsworthyEvent] = []
        for partition_dir in sorted(self._partitions_in_range(start.date(), end.date())):
            target = partition_dir / "events.parquet"
            if not target.exists():
                continue
            table = pq.read_table(target, schema=NEWSWORTHY_EVENTS_SCHEMA)
            for row in _rows(table):
                if row["status"] != status:
                    continue
                ts = row["ground_truth_timestamp"]
                if ts < start or ts > end:
                    continue
                events.append(_row_to_event(row))
        events.sort(key=lambda e: e.ground_truth_timestamp)
        return events

    def events_for_market(
        self, market_id: str, since: datetime, status: str = "labeled"
    ) -> list[NewsworthyEvent]:
        now = since + timedelta(days=365 * 10)  # effectively "until forever"
        window = self.events_in_window(since, now, status=status)
        return [event for event in window if market_id in event.market_ids]

    def coverage_by_category(self, since: datetime) -> dict[str, int]:
        now = since + timedelta(days=365 * 10)
        events = self.events_in_window(since, now)
        counter: Counter[str] = Counter()
        for event in events:
            counter[event.category] += 1
        return dict(counter)

    def _partitions_in_range(self, start: date, end: date) -> list[Path]:
        if not self._root.exists():
            return []
        selected: list[Path] = []
        for partition_dir in sorted(self._root.glob("date=*")):
            try:
                partition_date = date.fromisoformat(partition_dir.name.removeprefix("date="))
            except ValueError:
                continue
            if start <= partition_date <= end:
                selected.append(partition_dir)
        return selected


def _rows(table: Any) -> list[dict[str, Any]]:
    return [
        dict(zip(table.schema.names, row, strict=True))
        for row in zip(*[c.to_pylist() for c in table.columns], strict=True)
    ]


def _row_to_event(row: dict[str, Any]) -> NewsworthyEvent:
    return NewsworthyEvent(
        event_id=row["event_id"],
        ground_truth_timestamp=row["ground_truth_timestamp"],
        market_ids=list(row["market_ids"]),
        category=row["category"],
        headline=row["headline"],
        source_urls=list(row["source_urls"]),
        source_publishers=list(row["source_publishers"]),
        labeler_ids=list(row["labeler_ids"]),
        label_protocol_version=row["label_protocol_version"],
        corrects=row["corrects"],
        status=row["status"],
        created_at=row["created_at"],
    )
