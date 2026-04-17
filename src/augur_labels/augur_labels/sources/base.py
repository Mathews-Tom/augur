"""AbstractSourceAdapter protocol.

Every concrete wire-service adapter implements this surface so the
annotator CLI's ``discover`` command can fetch publications across
sources uniformly. Source-specific auth, rate-limiting, and response-
shape handling stay in the concrete adapter; callers see only
SourcePublication.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from augur_labels.models import SourcePublication
from augur_labels.models.source import SourceId


class AbstractSourceAdapter(Protocol):
    """Uniform interface every source adapter implements."""

    source_id: SourceId

    async def fetch_recent(
        self,
        since: datetime,
        keywords: Sequence[str] | None = None,
    ) -> list[SourcePublication]:
        """Return qualifying publications published since *since*.

        When *keywords* is provided, the adapter filters at the source
        where supported; otherwise it applies post-fetch filtering.
        """
        ...

    async def health_check(self) -> bool:
        """Verify credentials and connectivity."""
        ...
