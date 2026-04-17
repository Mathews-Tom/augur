"""Tests for the canonical JSON formatter."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from augur_format.deterministic.json_feed import (
    CANONICAL_KEY_ORDER,
    SIGNAL_KEY_ORDER,
    to_canonical_json,
)
from augur_signals.models import (
    InterpretationMode,
    ManipulationFlag,
    MarketSignal,
    RelatedMarketState,
    SignalContext,
    SignalType,
    new_signal_id,
)


def _signal() -> MarketSignal:
    return MarketSignal(
        signal_id=new_signal_id(),
        market_id="kalshi_fed",
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.8765432,
        direction=1,
        confidence=0.7219876,
        fdr_adjusted=True,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        manipulation_flags=[ManipulationFlag.SIZE_VS_DEPTH_OUTLIER],
        related_market_ids=["kalshi_fed_holds"],
        raw_features={
            "posterior_p_change": 0.9123456789,
            "calibration_provenance": "price_velocity_bocpd_beta_v1@identity_v0",
        },
    )


def _context() -> SignalContext:
    return SignalContext(
        signal=_signal(),
        market_question="Will the Fed raise rates in June 2026?",
        resolution_criteria="YES resolves if target range rises.",
        resolution_source="Federal Reserve press release",
        closes_at=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
        related_markets=[
            RelatedMarketState(
                market_id="kalshi_fed_holds",
                question="Will the Fed hold rates in June 2026?",
                current_price=0.44123,
                delta_24h=-0.0235432,
                volume_24h=85_000.0,
                relationship_type="inverse",
                relationship_strength=0.9,
            )
        ],
        investigation_prompts=["Check FOMC calendar.", "Check governor speeches."],
        interpretation_mode=InterpretationMode.DETERMINISTIC,
    )


@pytest.mark.unit
def test_byte_identical_across_1000_calls() -> None:
    ctx = _context()
    outputs = [to_canonical_json(ctx) for _ in range(1000)]
    assert all(o == outputs[0] for o in outputs)


@pytest.mark.unit
def test_floats_rounded_to_six_decimals() -> None:
    ctx = _context()
    payload = json.loads(to_canonical_json(ctx))
    # 0.9123456789 must round to 0.912346 at 6 decimals.
    provenance_payload = payload["signal"]["raw_features"]
    assert provenance_payload["posterior_p_change"] == 0.912346


@pytest.mark.unit
def test_custom_decimals_parameter_rounds_accordingly() -> None:
    ctx = _context()
    payload = json.loads(to_canonical_json(ctx, float_decimals=2))
    # 0.7219876 -> 0.72 at two decimals.
    assert payload["signal"]["confidence"] == 0.72


@pytest.mark.unit
def test_timestamps_use_z_suffix() -> None:
    ctx = _context()
    payload = json.loads(to_canonical_json(ctx))
    assert payload["signal"]["detected_at"].endswith("Z")
    assert "+00:00" not in payload["signal"]["detected_at"]
    assert payload["closes_at"].endswith("Z")


@pytest.mark.unit
def test_top_level_key_order_matches_canonical_tuple() -> None:
    ctx = _context()
    # json.loads preserves insertion order of keys; the outer dict's
    # key sequence is the canonical key ordering.
    payload = json.loads(to_canonical_json(ctx))
    assert list(payload.keys()) == list(CANONICAL_KEY_ORDER)


@pytest.mark.unit
def test_signal_key_order_matches_signal_tuple() -> None:
    ctx = _context()
    payload = json.loads(to_canonical_json(ctx))
    assert list(payload["signal"].keys()) == list(SIGNAL_KEY_ORDER)


@pytest.mark.unit
def test_related_market_fields_rounded() -> None:
    ctx = _context()
    payload = json.loads(to_canonical_json(ctx))
    rm = payload["related_markets"][0]
    # 0.44123 stays; -0.0235432 rounds to -0.023543
    assert rm["delta_24h"] == -0.023543


@pytest.mark.unit
def test_manipulation_flags_preserved_as_enum_values() -> None:
    ctx = _context()
    payload = json.loads(to_canonical_json(ctx))
    assert payload["signal"]["manipulation_flags"] == ["size_vs_depth_outlier"]
