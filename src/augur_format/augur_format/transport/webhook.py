"""Webhook adapter with JSON, Markdown, and Slack Block Kit formats.

Each WebhookTarget declares the URL, format, authorized consumer
types, and optional auth-header env var. The adapter POSTs the
formatted payload to the URL with exponential-backoff retry on 5xx /
429 / connection errors and drop on 4xx (logged as a configuration
error). Failed deliveries emit an error log with target_id and
signal_id for operational correlation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, HttpUrl

from augur_format._config import WebhookConfig
from augur_format.deterministic.json_feed import to_canonical_json
from augur_format.deterministic.markdown import MarkdownFormatter
from augur_format.deterministic.severity import derive_severity
from augur_format.transport.retry import (
    DeliveryBackoff,
    DeliveryRetryExhaustedError,
    deliver_with_backoff,
)
from augur_signals.models import SignalContext

WebhookFormat = Literal["json", "markdown", "slack_blocks"]


class WebhookTarget(BaseModel):
    """One configured webhook destination.

    Consumer-type gating and LLM-assisted opt-in live on the
    SignalRouter and the LLM formatter gate respectively; neither
    belongs on the delivery target, where there is no call site.
    Phase-4 re-introduces `accepts_llm_assisted` when the gated
    formatter needs per-target opt-in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str
    url: HttpUrl
    format: WebhookFormat
    auth_header_env: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Outcome of one webhook POST."""

    target_id: str
    status_code: int | None
    attempts: int
    delivered: bool
    reason: str


class WebhookFormatter:
    """POST payloads to configured webhook targets with retry."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: WebhookConfig | None = None,
        markdown: MarkdownFormatter | None = None,
    ) -> None:
        self._client = client
        self._config = config or WebhookConfig()
        self._markdown = markdown or MarkdownFormatter()

    def _backoff(self) -> DeliveryBackoff:
        return DeliveryBackoff(
            initial_seconds=self._config.initial_retry_delay_seconds,
            max_seconds=self._config.max_retry_delay_seconds,
            max_retries=self._config.max_retries,
        )

    def _render_body(self, context: SignalContext, target: WebhookTarget) -> bytes:
        if target.format == "json":
            return to_canonical_json(context)
        severity = derive_severity(context.signal)
        if target.format == "markdown":
            rendered = self._markdown.format(context, severity=severity)
            return json.dumps({"text": rendered}).encode("utf-8")
        # slack_blocks
        return json.dumps(self._slack_blocks(context, severity)).encode("utf-8")

    def _slack_blocks(self, context: SignalContext, severity: str) -> dict[str, Any]:
        signal = context.signal
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": (f"{signal.signal_type.value} | {severity} | {signal.confidence:.2f}"),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Market:* {context.market_question}\n"
                        f"*Resolution criteria:* {context.resolution_criteria}"
                    ),
                },
            },
        ]
        if context.related_markets:
            related_text = "\n".join(
                f"- *{rm.market_id}* ({rm.relationship_type}): {rm.current_price:.3f}"
                for rm in context.related_markets
            )
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": related_text}})
        if context.investigation_prompts:
            prompts_text = "\n".join(f"- {p}" for p in context.investigation_prompts)
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": prompts_text}})
        if signal.manipulation_flags:
            flags_text = ", ".join(f.value for f in signal.manipulation_flags)
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Manipulation flags: {flags_text}",
                        }
                    ],
                }
            )
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"Augur · {context.interpretation_mode.value} "
                            f"· schema {context.schema_version} "
                            f"· {signal.signal_id}"
                        ),
                    }
                ],
            }
        )
        return {"blocks": blocks}

    def _headers(self, target: WebhookTarget) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if target.auth_header_env:
            value = os.environ.get(target.auth_header_env)
            if value:
                headers["Authorization"] = value
        return headers

    async def deliver(self, context: SignalContext, target: WebhookTarget) -> DeliveryResult:
        body = self._render_body(context, target)
        headers = self._headers(target)

        async def _call() -> httpx.Response:
            response = await self._client.post(
                str(target.url),
                content=body,
                headers=headers,
                timeout=self._config.delivery_timeout_seconds,
            )
            if response.status_code >= 500 or response.status_code == 429:
                response.raise_for_status()
            return response

        try:
            response, attempts = await deliver_with_backoff(_call, self._backoff())
        except DeliveryRetryExhaustedError as err:
            return DeliveryResult(
                target_id=target.target_id,
                status_code=None,
                attempts=err.attempts,
                delivered=False,
                reason=repr(err.last_error),
            )
        delivered = 200 <= response.status_code < 400
        return DeliveryResult(
            target_id=target.target_id,
            status_code=response.status_code,
            attempts=attempts,
            delivered=delivered,
            reason="ok" if delivered else f"http_{response.status_code}",
        )
