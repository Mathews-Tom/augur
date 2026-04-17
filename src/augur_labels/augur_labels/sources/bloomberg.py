"""Bloomberg REST adapter.

Uses OAuth2 client-credentials flow driven by BLOOMBERG_CLIENT_ID and
BLOOMBERG_CLIENT_SECRET env vars. The token is acquired lazily on
first call and refreshed on 401 responses.
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


class BloombergAdapter:
    """Concrete AbstractSourceAdapter for Bloomberg."""

    source_id: SourceId = "bloomberg"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = "https://api.bloomberg.com/v1",
        token_url: str = "https://api.bloomberg.com/oauth2/token",  # noqa: S107
        client_id: str | None = None,
        client_secret: str | None = None,
        backoff: HttpBackoff | None = None,
    ) -> None:
        cid = client_id or os.environ.get("BLOOMBERG_CLIENT_ID")
        secret = client_secret or os.environ.get("BLOOMBERG_CLIENT_SECRET")
        if not cid or not secret:
            raise RuntimeError(
                "BloombergAdapter requires BLOOMBERG_CLIENT_ID and "
                "BLOOMBERG_CLIENT_SECRET environment variables"
            )
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url
        self._client_id = cid
        self._client_secret = secret
        self._backoff = backoff or HttpBackoff()
        self._token: str | None = None

    async def _ensure_token(self) -> str:
        if self._token is not None:
            return self._token

        async def _call() -> str:
            response = await self._client.post(
                self._token_url,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                timeout=30.0,
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            return str(payload["access_token"])

        token = await request_with_backoff(_call, self._backoff)
        self._token = token
        return token

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        token = await self._ensure_token()

        async def _call() -> dict[str, Any]:
            response = await self._client.get(
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=30.0,
            )
            if response.status_code == 401:
                # Force re-auth on next call.
                self._token = None
                response.raise_for_status()
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
            params["topic"] = ",".join(keywords)
        payload = await self._get("/news", params=params)
        return [_parse_publication(item) for item in payload.get("articles", [])]

    async def health_check(self) -> bool:
        try:
            await self._ensure_token()
        except Exception:
            return False
        return True


def _parse_publication(item: dict[str, Any]) -> SourcePublication:
    return SourcePublication(
        publication_id=str(item["id"]),
        source_id="bloomberg",
        timestamp=datetime.fromisoformat(str(item["published"]).replace("Z", "+00:00")),
        headline=str(item["headline"]),
        url=str(item["url"]),  # type: ignore[arg-type]
        body_excerpt=item.get("lead_paragraph"),
        keywords=list(item.get("topics", [])),
    )
