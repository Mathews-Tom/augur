"""Tests for the LLM prompt builder."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from augur_format.llm.prompts.builder import (
    PromptBuilder,
    PromptTemplateNotFoundError,
)
from augur_signals.models import (
    ConsumerType,
    InterpretationMode,
    ManipulationFlag,
    MarketSignal,
    RelatedMarketState,
    SignalContext,
    SignalType,
    new_signal_id,
)

FORBIDDEN = ["may be driven by", "likely reflects", "suggests that"]


def _context(
    signal_type: SignalType = SignalType.PRICE_VELOCITY,
    manipulation_flags: list[ManipulationFlag] | None = None,
    related: list[RelatedMarketState] | None = None,
) -> SignalContext:
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
        raw_features={"calibration_provenance": "d@identity_v0"},
    )
    return SignalContext(
        signal=signal,
        market_question="Will the Fed raise rates?",
        resolution_criteria="YES if rate rises.",
        resolution_source="Federal Reserve press release",
        closes_at=datetime(2026, 6, 15, tzinfo=UTC),
        related_markets=related or [],
        investigation_prompts=["Check FOMC calendar."],
        interpretation_mode=InterpretationMode.DETERMINISTIC,
    )


@pytest.fixture
def builder() -> PromptBuilder:
    return PromptBuilder(FORBIDDEN)


@pytest.mark.unit
def test_deterministic_across_calls(builder: PromptBuilder) -> None:
    ctx = _context()
    a = builder.build(ctx)
    b = builder.build(ctx)
    assert a == b


@pytest.mark.unit
def test_system_injects_forbidden_phrases(builder: PromptBuilder) -> None:
    system, _ = builder.build(_context())
    for phrase in FORBIDDEN:
        assert phrase in system


@pytest.mark.unit
def test_system_injects_full_consumer_enum(builder: PromptBuilder) -> None:
    system, _ = builder.build(_context())
    for consumer in ConsumerType:
        assert consumer.value in system


@pytest.mark.unit
def test_user_contains_verbatim_resolution_criteria(builder: PromptBuilder) -> None:
    _, user = builder.build(_context())
    assert "YES if rate rises." in user


@pytest.mark.unit
def test_manipulation_flags_reported_in_user(builder: PromptBuilder) -> None:
    _, user = builder.build(_context(manipulation_flags=[ManipulationFlag.SIZE_VS_DEPTH_OUTLIER]))
    assert "size_vs_depth_outlier" in user


@pytest.mark.unit
def test_none_flags_render_as_placeholder(builder: PromptBuilder) -> None:
    _, user = builder.build(_context())
    assert "Manipulation flags: (none)" in user


@pytest.mark.unit
def test_every_signal_type_has_a_template(builder: PromptBuilder) -> None:
    for signal_type in SignalType:
        _, user = builder.build(_context(signal_type=signal_type))
        assert f"Signal type: {signal_type.value}" in user


@pytest.mark.unit
def test_related_markets_render_as_bullets(builder: PromptBuilder) -> None:
    related = [
        RelatedMarketState(
            market_id="kalshi_fed_holds",
            question="?",
            current_price=0.42,
            delta_24h=-0.02,
            volume_24h=1000.0,
            relationship_type="inverse",
            relationship_strength=0.9,
        )
    ]
    _, user = builder.build(_context(related=related))
    assert "kalshi_fed_holds" in user


@pytest.mark.unit
def test_missing_template_raises(tmp_path: object) -> None:
    import shutil

    from augur_format.llm.prompts.builder import _DEFAULT_TEMPLATE_DIR

    isolated = tmp_path  # type: ignore[assignment]
    isolated_path = isolated  # appease mypy; tmp_path is Path in practice.
    assert isolated_path  # keep name
    target = tmp_path / "templates"  # type: ignore[operator]
    shutil.copytree(_DEFAULT_TEMPLATE_DIR, target)
    (target / "price_velocity.txt").unlink()
    builder = PromptBuilder(FORBIDDEN, template_dir=target)
    with pytest.raises(PromptTemplateNotFoundError):
        builder.build(_context())
