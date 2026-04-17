"""Jinja2 Markdown renderer.

Templates live alongside this module at ``templates/``; one per
signal type plus a shared ``_base.md.j2``. The renderer is
deterministic given identical inputs and template files. The
templates are committed, so any rendering drift surfaces as a test
failure rather than silent variation.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from augur_signals.models import SignalContext

_DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class MarkdownFormatter:
    """Render a SignalContext as Markdown via Jinja2."""

    def __init__(self, template_dir: Path | None = None) -> None:
        directory = template_dir or _DEFAULT_TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(directory)),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def format(self, context: SignalContext, severity: str) -> str:
        """Render the per-signal-type template for *context*.

        Raises jinja2.TemplateNotFound if the signal_type does not
        have a dedicated template; a dedicated template exists for
        every value in SignalType by construction, so missing
        templates indicate a contract drift between enum and templates.
        """
        template_name = f"{context.signal.signal_type.value}.md.j2"
        template = self._env.get_template(template_name)
        return template.render(
            signal=context.signal,
            market_question=context.market_question,
            resolution_criteria=context.resolution_criteria,
            resolution_source=context.resolution_source,
            closes_at=context.closes_at,
            related_markets=context.related_markets,
            investigation_prompts=context.investigation_prompts,
            interpretation_mode=context.interpretation_mode.value,
            schema_version=context.schema_version,
            severity=severity,
        )
