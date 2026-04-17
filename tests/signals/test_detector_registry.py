"""Tests for the detector registry's dispatch surface."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from augur_signals.detectors.registry import DetectorRegistry
from augur_signals.models import (
    FeatureVector,
    MarketSignal,
    MarketSnapshot,
    SignalType,
    new_signal_id,
)


class _FireEveryTick:
    detector_id = "fixture_fire_every_tick"
    signal_type = SignalType.PRICE_VELOCITY

    def warmup_required(self) -> int:
        return 0

    def ingest(
        self,
        market_id: str,
        feature: FeatureVector,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> MarketSignal | None:
        return MarketSignal(
            signal_id=new_signal_id(),
            market_id=market_id,
            platform=snapshot.platform,
            signal_type=self.signal_type,
            magnitude=0.9,
            direction=1,
            confidence=0.9,
            fdr_adjusted=False,
            detected_at=now,
            window_seconds=300,
            liquidity_tier="high",
            raw_features={"calibration_provenance": f"{self.detector_id}@identity_v0"},
        )

    def state_dict(self, market_id: str) -> dict[str, Any]:
        return {}

    def load_state(self, market_id: str, state: dict[str, Any]) -> None:
        return None

    def reset(self, market_id: str) -> None:
        return None


class _NeverFire(_FireEveryTick):
    detector_id = "fixture_never_fire"

    def ingest(
        self,
        market_id: str,
        feature: FeatureVector,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> MarketSignal | None:
        return None


def _feature() -> FeatureVector:
    return FeatureVector(
        market_id="m",
        computed_at=datetime(2026, 3, 15, tzinfo=UTC),
        price_momentum_5m=0.0,
        price_momentum_15m=0.0,
        price_momentum_1h=0.0,
        price_momentum_4h=0.0,
        volatility_5m=0.0,
        volatility_15m=0.0,
        volatility_1h=0.0,
        volatility_4h=0.0,
        volume_ratio_5m=1.0,
        volume_ratio_1h=1.0,
        bid_ask_ratio=0.5,
        spread_pct=0.01,
    )


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        market_id="m",
        platform="kalshi",
        timestamp=datetime(2026, 3, 15, tzinfo=UTC),
        last_price=0.5,
        bid=0.49,
        ask=0.51,
        spread=0.02,
        volume_24h=100000.0,
        liquidity=5000.0,
        question="q",
        resolution_source=None,
        resolution_criteria=None,
        closes_at=None,
        raw_json={},
    )


@pytest.mark.unit
def test_registry_dispatches_to_every_detector() -> None:
    reg = DetectorRegistry()
    reg.register(_FireEveryTick())
    reg.register(_NeverFire())
    signals = reg.dispatch("m", _feature(), _snapshot(), datetime(2026, 3, 15, tzinfo=UTC))
    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.PRICE_VELOCITY


@pytest.mark.unit
def test_registry_warmup_required_is_max() -> None:
    reg = DetectorRegistry()

    class _Hundred(_FireEveryTick):
        def warmup_required(self) -> int:
            return 100

    class _Fifty(_FireEveryTick):
        def warmup_required(self) -> int:
            return 50

    reg.register(_Fifty())
    reg.register(_Hundred())
    assert reg.warmup_required() == 100
