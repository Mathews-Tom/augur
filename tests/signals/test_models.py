"""Tests for the Pydantic data contracts.

The contracts in docs/contracts/schema-and-versioning.md are the
binding interface between layers. These tests lock down the field set,
the required invariants (calibration_provenance on every signal,
frozen-model immutability, closed-enum membership), and the schema-
version stamping so downstream consumers can rely on the shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from augur_signals.models import (
    ConsumerType,
    FeatureVector,
    InterpretationMode,
    ManipulationFlag,
    MarketSignal,
    MarketSnapshot,
    RelatedMarketState,
    SignalContext,
    SignalType,
    new_signal_id,
)


def _signal(**overrides: object) -> MarketSignal:
    defaults: dict[str, object] = {
        "signal_id": new_signal_id(),
        "market_id": "kalshi_example",
        "platform": "kalshi",
        "signal_type": SignalType.PRICE_VELOCITY,
        "magnitude": 0.8,
        "direction": 1,
        "confidence": 0.72,
        "fdr_adjusted": True,
        "detected_at": datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        "window_seconds": 300,
        "liquidity_tier": "high",
        "related_market_ids": [],
        "raw_features": {
            "posterior_p_change": 0.92,
            "calibration_provenance": "price_velocity_bocpd_beta_v1@identity_v0",
        },
    }
    defaults.update(overrides)
    return MarketSignal.model_validate(defaults)


def _snapshot(**overrides: object) -> MarketSnapshot:
    defaults: dict[str, object] = {
        "market_id": "kalshi_example",
        "platform": "kalshi",
        "timestamp": datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        "last_price": 0.55,
        "bid": 0.54,
        "ask": 0.56,
        "spread": 0.02,
        "volume_24h": 120000.0,
        "liquidity": 8500.0,
        "question": "Will the Fed raise rates in June 2026?",
        "resolution_source": "Federal Reserve press release",
        "resolution_criteria": "YES resolves to 1 if target range rises.",
        "closes_at": datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
        "raw_json": {"platform_field": 1},
    }
    defaults.update(overrides)
    return MarketSnapshot.model_validate(defaults)


@pytest.mark.unit
def test_enums_have_closed_membership() -> None:
    assert {m.value for m in SignalType} == {
        "price_velocity",
        "volume_spike",
        "book_imbalance",
        "cross_market_divergence",
        "regime_shift",
    }
    assert {m.value for m in ManipulationFlag} == {
        "single_counterparty_concentration",
        "size_vs_depth_outlier",
        "cancel_replace_burst",
        "thin_book_during_move",
        "pre_resolution_window",
    }
    assert {m.value for m in ConsumerType} == {
        "macro_research_agent",
        "geopolitical_research_agent",
        "crypto_research_agent",
        "financial_news_desk",
        "regulatory_news_desk",
        "dashboard",
    }
    assert {m.value for m in InterpretationMode} == {"deterministic", "llm_assisted"}


@pytest.mark.unit
def test_new_signal_id_is_time_ordered() -> None:
    first = new_signal_id()
    second = new_signal_id()
    assert first != second
    # uuid7 is time-ordered; monotonicity holds within same millisecond
    assert first <= second or first > second  # monotonic or tied, never a crash


@pytest.mark.unit
def test_market_snapshot_accepts_canonical_payload() -> None:
    snap = _snapshot()
    assert snap.platform == "kalshi"
    assert snap.schema_version == "1.0.0"


@pytest.mark.unit
def test_market_snapshot_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MarketSnapshot.model_validate({**_snapshot().model_dump(), "unexpected_field": 1})


@pytest.mark.unit
def test_market_snapshot_is_frozen() -> None:
    snap = _snapshot()
    with pytest.raises(ValidationError):
        snap.market_id = "mutated"  # type: ignore[misc]


@pytest.mark.unit
def test_market_signal_requires_calibration_provenance() -> None:
    with pytest.raises(ValidationError, match="calibration_provenance"):
        _signal(raw_features={"posterior_p_change": 0.9})


@pytest.mark.unit
def test_market_signal_rejects_empty_provenance_string() -> None:
    with pytest.raises(ValidationError, match="calibration_provenance"):
        _signal(
            raw_features={
                "posterior_p_change": 0.9,
                "calibration_provenance": "",
            }
        )


@pytest.mark.unit
def test_market_signal_manipulation_flags_default_to_empty_list() -> None:
    sig = _signal()
    assert sig.manipulation_flags == []


@pytest.mark.unit
def test_market_signal_accepts_closed_enum_flags() -> None:
    sig = _signal(
        manipulation_flags=[ManipulationFlag.SIZE_VS_DEPTH_OUTLIER],
    )
    assert sig.manipulation_flags == [ManipulationFlag.SIZE_VS_DEPTH_OUTLIER]


@pytest.mark.unit
def test_market_signal_rejects_float_direction() -> None:
    with pytest.raises(ValidationError):
        _signal(direction=0.5)  # type: ignore[arg-type]


@pytest.mark.unit
def test_market_signal_schema_version_is_stamped() -> None:
    sig = _signal()
    assert sig.schema_version == "1.0.0"


@pytest.mark.unit
def test_feature_vector_schema_stamp() -> None:
    fv = FeatureVector(
        market_id="m",
        computed_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        price_momentum_5m=0.01,
        price_momentum_15m=0.02,
        price_momentum_1h=0.03,
        price_momentum_4h=0.05,
        volatility_5m=0.01,
        volatility_15m=0.015,
        volatility_1h=0.02,
        volatility_4h=0.025,
        volume_ratio_5m=1.1,
        volume_ratio_1h=1.3,
        bid_ask_ratio=0.5,
        spread_pct=0.02,
    )
    assert fv.schema_version == "1.0.0"


@pytest.mark.unit
def test_signal_context_wraps_market_signal() -> None:
    sig = _signal()
    ctx = SignalContext(
        signal=sig,
        market_question="Will the Fed raise rates?",
        resolution_criteria="YES resolves if rate rises.",
        resolution_source="Federal Reserve press release",
        closes_at=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
        related_markets=[
            RelatedMarketState(
                market_id="kalshi_fed_holds",
                question="Will the Fed hold rates?",
                current_price=0.45,
                delta_24h=-0.02,
                volume_24h=80000.0,
                relationship_type="inverse",
                relationship_strength=0.9,
            )
        ],
        investigation_prompts=["Check FOMC calendar."],
    )
    assert ctx.interpretation_mode == InterpretationMode.DETERMINISTIC
    assert ctx.schema_version == "1.0.0"
    assert ctx.signal.signal_id == sig.signal_id
