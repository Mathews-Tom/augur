"""Tests for the Markdown formatter."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from augur_format.deterministic.markdown import MarkdownFormatter
from augur_signals.models import (
    InterpretationMode,
    ManipulationFlag,
    MarketSignal,
    RelatedMarketState,
    SignalContext,
    SignalType,
    new_signal_id,
)

_UNSET_PROMPTS: list[str] = ["Check FOMC calendar."]


def _context(
    signal_type: SignalType = SignalType.PRICE_VELOCITY,
    raw_features: dict[str, float | str] | None = None,
    manipulation_flags: list[ManipulationFlag] | None = None,
    related: list[RelatedMarketState] | None = None,
    prompts: list[str] | None = None,
) -> SignalContext:
    rf: dict[str, float | str] = {
        "calibration_provenance": f"{signal_type.value}_detector@identity_v0",
        "posterior_p_change": 0.82,
        "z_score": 2.3,
        "spearman_rho": -0.45,
        "positive_cusum": 3.1,
        "negative_cusum": -0.2,
        "threshold": 2.5,
        "bid_ask_ratio": 0.75,
        "liquidity": 12000.0,
        "ewma_mean": 1.2,
        "volume_ratio_1h": 3.5,
        "historical_z": 1.8,
        "p_value": 0.01,
        "related_market_id": "kalshi_fed_holds",
    }
    if raw_features:
        rf.update(raw_features)
    signal = MarketSignal(
        signal_id=new_signal_id(),
        market_id="kalshi_fed",
        platform="kalshi",
        signal_type=signal_type,
        magnitude=0.8,
        direction=1,
        confidence=0.72,
        fdr_adjusted=True,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        manipulation_flags=manipulation_flags or [],
        raw_features=rf,
    )
    return SignalContext(
        signal=signal,
        market_question="Will the Fed raise rates?",
        resolution_criteria="YES if rate rises.",
        resolution_source="Federal Reserve press release",
        closes_at=datetime(2026, 6, 15, tzinfo=UTC),
        related_markets=related or [],
        investigation_prompts=_UNSET_PROMPTS if prompts is None else prompts,
        interpretation_mode=InterpretationMode.DETERMINISTIC,
    )


@pytest.fixture
def formatter() -> MarkdownFormatter:
    return MarkdownFormatter()


@pytest.mark.unit
def test_every_signal_type_renders(formatter: MarkdownFormatter) -> None:
    for signal_type in SignalType:
        md = formatter.format(_context(signal_type=signal_type), severity="medium")
        assert md.startswith("# ")
        assert "Signal Summary" in md


@pytest.mark.unit
def test_renders_required_fields(formatter: MarkdownFormatter) -> None:
    md = formatter.format(_context(), severity="high")
    assert "**Severity:** high" in md
    assert "Will the Fed raise rates?" in md
    assert "Federal Reserve press release" in md
    assert "Investigation Prompts" in md
    assert "Check FOMC calendar." in md


@pytest.mark.unit
def test_manipulation_flag_block_appears_when_flags_present(
    formatter: MarkdownFormatter,
) -> None:
    md = formatter.format(
        _context(manipulation_flags=[ManipulationFlag.SIZE_VS_DEPTH_OUTLIER]),
        severity="medium",
    )
    assert "Manipulation Flags" in md
    assert "size_vs_depth_outlier" in md


@pytest.mark.unit
def test_manipulation_flag_block_absent_when_empty(
    formatter: MarkdownFormatter,
) -> None:
    md = formatter.format(_context(), severity="medium")
    assert "Manipulation Flags" not in md


@pytest.mark.unit
def test_related_markets_render_as_bullets(formatter: MarkdownFormatter) -> None:
    related = [
        RelatedMarketState(
            market_id="kalshi_fed_holds",
            question="Will the Fed hold?",
            current_price=0.42,
            delta_24h=-0.03,
            volume_24h=80_000.0,
            relationship_type="inverse",
            relationship_strength=0.9,
        )
    ]
    md = formatter.format(_context(related=related), severity="medium")
    assert "**kalshi_fed_holds** (inverse," in md
    assert "No related markets" not in md


@pytest.mark.unit
def test_fallback_text_when_no_related_markets(formatter: MarkdownFormatter) -> None:
    md = formatter.format(_context(), severity="medium")
    assert "No related markets in the curated taxonomy." in md


@pytest.mark.unit
def test_fallback_text_when_no_investigation_prompts(
    formatter: MarkdownFormatter,
) -> None:
    md = formatter.format(_context(prompts=[]), severity="medium")
    assert "No investigation prompts configured for this (signal_type, category) tuple." in md


@pytest.mark.unit
def test_markdown_deterministic_across_calls(formatter: MarkdownFormatter) -> None:
    ctx = _context()
    outputs = {formatter.format(ctx, severity="medium") for _ in range(100)}
    assert len(outputs) == 1
