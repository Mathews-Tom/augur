"""Reuters REST adapter.

Uses the REUTERS_API_KEY env var for Bearer auth; the adapter is
deliberately thin so replay-fixture tests can exercise the parse path
without real credentials. A missing API key fails loud at construction
rather than silently returning an empty list.
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


class ReutersAdapter:
    """Concrete AbstractSourceAdapter implementation for Reuters."""

    source_id: SourceId = "reuters"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = "https://api.reuters.com/v1",
        api_key: str | None = None,
        backoff: HttpBackoff | None = None,
    ) -> None:
        key = api_key or os.environ.get("REUTERS_API_KEY")
        if not key:
            raise RuntimeError("ReutersAdapter requires REUTERS_API_KEY environment variable")
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._api_key = key
        self._backoff = backoff or HttpBackoff()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
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
        params = {"since": since.isoformat().replace("+00:00", "Z")}
        if keywords:
            params["q"] = " ".join(keywords)
        payload = await self._get("/articles", params=params)
        return [_parse_publication(item) for item in payload.get("articles", [])]

    async def health_check(self) -> bool:
        try:
            await self._get("/health")
        except Exception:
            return False
        return True


def _parse_publication(item: dict[str, Any]) -> SourcePublication:
    return SourcePublication(
        publication_id=str(item["id"]),
        source_id="reuters",
        timestamp=datetime.fromisoformat(str(item["published_at"]).replace("Z", "+00:00")),
        headline=str(item["title"]),
        url=str(item["url"]),  # type: ignore[arg-type]
        body_excerpt=item.get("summary"),
        keywords=list(item.get("keywords", [])),
    )
