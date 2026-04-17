"""Per-market snapshot buffer used by the feature pipeline.

The buffer keeps the most recent N snapshots with O(1) append and O(k)
window retrieval. Window queries are observation-count internally; the
wall-clock window labels in docs/contracts/schema-and-versioning.md are
mapped via the current polling interval per
docs/architecture/adaptive-polling-spec.md §Wall-Clock vs
Observation-Count Window Reconciliation.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from augur_signals.models import MarketSnapshot


class SnapshotBuffer:
    """Bounded deque of recent MarketSnapshot for one market."""

    def __init__(self, max_size: int = 1000) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._buffer: deque[MarketSnapshot] = deque(maxlen=max_size)

    def append(self, snapshot: MarketSnapshot) -> None:
        self._buffer.append(snapshot)

    def extend(self, snapshots: Iterable[MarketSnapshot]) -> None:
        for snap in snapshots:
            self._buffer.append(snap)

    def window(self, n: int) -> list[MarketSnapshot]:
        """Return the most recent *n* snapshots (or fewer if not ready)."""
        if n <= 0:
            return []
        if n >= len(self._buffer):
            return list(self._buffer)
        return list(self._buffer)[-n:]

    def latest(self) -> MarketSnapshot | None:
        return self._buffer[-1] if self._buffer else None

    def __len__(self) -> int:
        return len(self._buffer)
