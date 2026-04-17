"""Identifier helpers for signals and related entities.

`uuid7` is time-ordered, which lets the bus, storage, and archive
sort by identifier and still recover temporal order. This is load-
bearing for backtest replay determinism: the (detected_at, signal_id)
pair is stable and reproducible.
"""

from __future__ import annotations

from uuid_extensions import uuid7


def new_signal_id() -> str:
    """Generate a time-ordered uuid7 signal identifier."""
    return str(uuid7())
