"""Tests for the append-only Parquet writer and reader."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from augur_labels.models import NewsworthyEvent
from augur_labels.storage.parquet_writer import AppendOnlyParquetWriter
from augur_labels.storage.reader import LabelReader


def _event(
    event_id: str,
    offset_days: int = 0,
    market_ids: list[str] | None = None,
    status: str = "labeled",
    corrects: str | None = None,
) -> NewsworthyEvent:
    return NewsworthyEvent(
        event_id=event_id,
        ground_truth_timestamp=datetime(2026, 3, 15 + offset_days, 12, 0, tzinfo=UTC),
        market_ids=market_ids or ["kalshi_fed"],
        category="monetary_policy",
        headline=f"Event {event_id}",
        source_urls=["https://a", "https://b"],
        source_publishers=["reuters", "bloomberg"],
        labeler_ids=["ann1", "ann2"],
        label_protocol_version="1.0",
        corrects=corrects,
        status=status,  # type: ignore[arg-type]
        created_at=datetime(2026, 3, 16, tzinfo=UTC),
    )


@pytest.mark.unit
def test_writer_appends_single_event(tmp_path: Path) -> None:
    writer = AppendOnlyParquetWriter(tmp_path)
    writer.append([_event("e1")])
    partition = tmp_path / "date=2026-03-15" / "events.parquet"
    assert partition.exists()


@pytest.mark.unit
def test_writer_appends_across_partitions(tmp_path: Path) -> None:
    writer = AppendOnlyParquetWriter(tmp_path)
    writer.append([_event("e1", offset_days=0), _event("e2", offset_days=1)])
    assert (tmp_path / "date=2026-03-15" / "events.parquet").exists()
    assert (tmp_path / "date=2026-03-16" / "events.parquet").exists()


@pytest.mark.unit
def test_writer_appends_are_idempotent_across_calls(tmp_path: Path) -> None:
    writer = AppendOnlyParquetWriter(tmp_path)
    writer.append([_event("e1")])
    writer.append([_event("e2")])
    reader = LabelReader(tmp_path)
    events = reader.events_in_window(
        datetime(2026, 3, 1, tzinfo=UTC),
        datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert {e.event_id for e in events} == {"e1", "e2"}


@pytest.mark.unit
def test_writer_supersede_updates_status(tmp_path: Path) -> None:
    writer = AppendOnlyParquetWriter(tmp_path)
    writer.append([_event("e1")])
    writer.append([_event("e2")])
    writer.supersede("e1", replacement_id="e2")
    reader = LabelReader(tmp_path)
    superseded = reader.events_in_window(
        datetime(2026, 3, 1, tzinfo=UTC),
        datetime(2026, 3, 31, tzinfo=UTC),
        status="superseded",
    )
    assert len(superseded) == 1
    assert superseded[0].event_id == "e1"
    assert superseded[0].corrects == "e2"


@pytest.mark.unit
def test_writer_supersede_missing_raises(tmp_path: Path) -> None:
    writer = AppendOnlyParquetWriter(tmp_path)
    with pytest.raises(KeyError, match="missing"):
        writer.supersede("missing", replacement_id="e2")


@pytest.mark.unit
def test_reader_events_for_market_filters(tmp_path: Path) -> None:
    writer = AppendOnlyParquetWriter(tmp_path)
    writer.append(
        [
            _event("e1", market_ids=["kalshi_fed"]),
            _event("e2", market_ids=["kalshi_other"]),
        ]
    )
    reader = LabelReader(tmp_path)
    fed_events = reader.events_for_market(
        "kalshi_fed", since=datetime(2026, 3, 1, tzinfo=UTC)
    )
    assert [e.event_id for e in fed_events] == ["e1"]


@pytest.mark.unit
def test_reader_coverage_by_category(tmp_path: Path) -> None:
    writer = AppendOnlyParquetWriter(tmp_path)
    writer.append([_event("e1"), _event("e2", offset_days=1)])
    reader = LabelReader(tmp_path)
    coverage = reader.coverage_by_category(since=datetime(2026, 3, 1, tzinfo=UTC))
    assert coverage == {"monetary_policy": 2}


@pytest.mark.unit
def test_reader_returns_empty_on_no_root(tmp_path: Path) -> None:
    reader = LabelReader(tmp_path / "does-not-exist")
    events = reader.events_in_window(
        datetime(2026, 3, 1, tzinfo=UTC),
        datetime(2026, 3, 31, tzinfo=UTC),
    )
    assert events == []
