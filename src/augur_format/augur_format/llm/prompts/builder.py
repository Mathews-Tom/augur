"""Structured prompt builder.

Produces a deterministic (system, user) pair for any SignalContext.
The system message embeds the forbidden phrase list, a summary of
the IntelligenceBrief schema, and the ConsumerType enum. The user
message renders the signal payload into the per-signal-type
template.

The builder is deterministic: identical SignalContext + identical
forbidden-phrase list + identical template files always produce
identical prompt strings. The prompt hash used for provenance is
the SHA-256 of `system + "\\n\\n" + user`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from augur_format.llm.models import SCHEMA_VERSION
from augur_signals.models import ConsumerType, SignalContext

_DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class PromptTemplateNotFoundError(RuntimeError):
    """Raised when the signal type has no corresponding template file."""


class PromptBuilder:
    """Deterministic (system, user) prompt construction."""

    def __init__(
        self,
        forbidden_phrases: Sequence[str],
        template_dir: Path | None = None,
    ) -> None:
        directory = template_dir or _DEFAULT_TEMPLATE_DIR
        system_path = directory / "_system.txt"
        if not system_path.exists():
            raise PromptTemplateNotFoundError(f"system template missing at {system_path}")
        self._template_dir = directory
        self._forbidden_phrases = sorted(forbidden_phrases)
        self._system_template = system_path.read_text(encoding="utf-8")

    def build(self, context: SignalContext) -> tuple[str, str]:
        """Return the (system_prompt, user_prompt) pair for *context*."""
        system = self._render_system()
        user = self._render_user(context)
        return system, user

    def _render_system(self) -> str:
        phrases = "\n".join(f"- {phrase}" for phrase in self._forbidden_phrases)
        consumers = "\n".join(f"- {c.value}" for c in ConsumerType)
        return self._system_template.format(
            forbidden_phrases_list=phrases,
            intelligence_brief_schema=_BRIEF_SCHEMA_SUMMARY,
            consumer_type_enum=consumers,
        )

    def _render_user(self, context: SignalContext) -> str:
        template_name = f"{context.signal.signal_type.value}.txt"
        template_path = self._template_dir / template_name
        if not template_path.exists():
            raise PromptTemplateNotFoundError(
                f"no template for signal_type={context.signal.signal_type.value!r}"
            )
        template = template_path.read_text(encoding="utf-8")
        related = (
            "\n".join(
                f"- {rm.market_id} ({rm.relationship_type}, strength {rm.relationship_strength}): "
                f"price {rm.current_price}, 24h delta {rm.delta_24h}"
                for rm in context.related_markets
            )
            or "(none)"
        )
        prompts = "\n".join(f"- {prompt}" for prompt in context.investigation_prompts) or "(none)"
        flags = ",".join(flag.value for flag in context.signal.manipulation_flags) or "(none)"
        return template.format(
            market_id=context.signal.market_id,
            platform=context.signal.platform,
            market_question=context.market_question,
            magnitude=f"{context.signal.magnitude:.6f}",
            direction=context.signal.direction,
            confidence=f"{context.signal.confidence:.6f}",
            fdr_adjusted=context.signal.fdr_adjusted,
            liquidity_tier=context.signal.liquidity_tier,
            window_seconds=context.signal.window_seconds,
            detected_at=context.signal.detected_at.isoformat().replace("+00:00", "Z"),
            resolution_criteria=context.resolution_criteria,
            resolution_source=context.resolution_source,
            closes_at=context.closes_at.isoformat().replace("+00:00", "Z"),
            manipulation_flags_csv_or_none=flags,
            related_markets_block=related,
            investigation_prompts_block=prompts,
        )


_BRIEF_SCHEMA_SUMMARY: str = (
    "- brief_id: string (uuid7)\n"
    "- signal_id: string\n"
    "- headline: string (max 90 chars)\n"
    "- body_markdown: string (max 800 chars)\n"
    "- severity: one of [high, medium, low]\n"
    "- actionable_for: list of ConsumerType\n"
    "- interpretation_mode: must equal 'llm_assisted'\n"
    "- model: string\n"
    "- prompt_hash: string (sha256 hex)\n"
    "- formatter_version: string\n"
    "- generated_at: ISO-8601 UTC datetime\n"
    "- forbidden_token_check: must equal 'passed'\n"
    f"- schema_version: '{SCHEMA_VERSION}'"
)
