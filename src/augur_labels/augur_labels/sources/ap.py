"""Associated Press REST adapter.

Uses the AP_API_KEY env var. Coverage is broad but throughput is
lower than Reuters; the rate_limit_per_hour in config/labeling.toml
caps concurrent discovery runs.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import httpx

from augur_labels.models import SourcePublication
from augur_labels.models.source import SourceId
from augur_labels.sources._http import HttpBackoff, request_with_backoff


class ApAdapter:
    """Concrete AbstractSourceAdapter for Associated Press."""

    source_id: SourceId = "ap"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = "https://api.ap.org/v1",
        api_key: str | None = None,
        backoff: HttpBackoff | None = None,
    ) -> None:
        key = api_key or os.environ.get("AP_API_KEY")
        if not key:
            raise RuntimeError("ApAdapter requires AP_API_KEY environment variable")
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_key = key
        self._backoff = backoff or HttpBackoff()

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        merged = {"apikey": self._api_key, **(params or {})}

        async def _call() -> dict[str, Any]:
            response = await self._client.get(
                f"{self._base_url}{path}", params=merged, timeout=30.0
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

        return await request_with_backoff(_call, self._backoff)

    async def fetch_recent(
        self,
        since: datetime,
        keywords: Sequence[str] | None = None,
    ) -> list[SourcePublication]:
        params = {"min_date": since.isoformat().replace("+00:00", "Z")}
        if keywords:
            params["q"] = " ".join(keywords)
        payload = await self._get("/content/search", params=params)
        return [_parse_publication(item) for item in payload.get("items", [])]

    async def health_check(self) -> bool:
        try:
            await self._get("/content/search", params={"min_date": "1970-01-01T00:00:00Z"})
        except Exception:
            return False
        return True


def _parse_publication(item: dict[str, Any]) -> SourcePublication:
    return SourcePublication(
        publication_id=str(item["itemid"]),
        source_id="ap",
        timestamp=datetime.fromisoformat(str(item["firstcreated"]).replace("Z", "+00:00")),
        headline=str(item["headline"]),
        url=str(item["link"]),  # type: ignore[arg-type]
        body_excerpt=item.get("summary"),
        keywords=list(item.get("subject", [])),
    )
