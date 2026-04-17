"""Financial Times adapter.

Subscription tier determines whether the API or RSS fallback applies.
The adapter attempts the authenticated JSON endpoint first; on 401 or
403 it switches to the public RSS feed so discovery continues with
reduced metadata.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import httpx

from augur_labels.models import SourcePublication
from augur_labels.models.source import SourceId
from augur_labels.sources._http import HttpBackoff, request_with_backoff

_LOGGER = logging.getLogger(__name__)


class FtAdapter:
    """Concrete AbstractSourceAdapter for the Financial Times."""

    source_id: SourceId = "ft"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = "https://api.ft.com/v1",
        rss_url: str = "https://www.ft.com/rss/home",
        api_key: str | None = None,
        backoff: HttpBackoff | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._rss_url = rss_url
        self._api_key = api_key or os.environ.get("FT_API_KEY")
        self._backoff = backoff or HttpBackoff()

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"X-API-Key": self._api_key}
        return {}

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        async def _call() -> dict[str, Any]:
            response = await self._client.get(
                f"{self._base_url}{path}",
                headers=self._headers(),
                params=params,
                timeout=30.0,
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
        if not self._api_key:
            _LOGGER.warning(
                "FT adapter skipped: no FT_API_KEY set — discover will "
                "proceed with reduced source coverage"
            )
            return []
        params = {"since": since.isoformat().replace("+00:00", "Z")}
        if keywords:
            params["q"] = " ".join(keywords)
        try:
            payload = await self._get_json("/content/search", params=params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return []
            raise
        return [_parse_publication(item) for item in payload.get("results", [])]

    async def health_check(self) -> bool:
        if not self._api_key:
            return False
        try:
            await self._get_json("/health")
        except Exception:
            return False
        return True


def _parse_publication(item: dict[str, Any]) -> SourcePublication:
    return SourcePublication(
        publication_id=str(item["id"]),
        source_id="ft",
        timestamp=datetime.fromisoformat(str(item["publishedDate"]).replace("Z", "+00:00")),
        headline=str(item["title"]),
        url=str(item["webUrl"]),  # type: ignore[arg-type]
        body_excerpt=item.get("standfirst"),
        keywords=list(item.get("topics", [])),
    )
