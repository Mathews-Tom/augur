"""Pyarrow schema for newsworthy_events.parquet.

Columns mirror the table in docs/methodology/labeling-protocol.md
§Storage Schema verbatim. The schema is frozen at protocol version 1.0;
a change to any column requires a label_protocol_version bump and a
recomputation of any calibration metric derived from the affected
labels.
"""

from __future__ import annotations

import pyarrow as pa

NEWSWORTHY_EVENTS_SCHEMA: pa.Schema = pa.schema(
    [
        ("event_id", pa.string()),
        ("ground_truth_timestamp", pa.timestamp("us", tz="UTC")),
        ("market_ids", pa.list_(pa.string())),
        ("category", pa.string()),
        ("headline", pa.string()),
        ("source_urls", pa.list_(pa.string())),
        ("source_publishers", pa.list_(pa.string())),
        ("labeler_ids", pa.list_(pa.string())),
        ("label_protocol_version", pa.string()),
        ("corrects", pa.string()),
        ("status", pa.string()),
        ("created_at", pa.timestamp("us", tz="UTC")),
    ]
)
