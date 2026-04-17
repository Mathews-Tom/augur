"""Tests for the adaptive polling scheduler state machine."""

from __future__ import annotations

import pytest

from augur_signals.ingestion._config import PollingBody, PollingConfig
from augur_signals.ingestion.scheduler import AdaptivePollingScheduler


@pytest.fixture
def scheduler() -> AdaptivePollingScheduler:
    body = PollingBody()
    sched = AdaptivePollingScheduler(body)
    sched.register("market-a", initial_tier="cool")
    return sched


@pytest.mark.unit
def test_polling_config_loads_from_toml_matching_spec() -> None:
    cfg = PollingConfig.model_validate(
        {
            "polling": {
                "hot_interval_s": 15,
                "warm_interval_s": 30,
                "cool_interval_s": 60,
                "cold_interval_s": 300,
            }
        }
    )
    assert cfg.polling.hot_interval_s == 15
    assert cfg.polling.hysteresis.hot_promote == 2.2


@pytest.mark.unit
def test_initial_tier_maps_to_interval(scheduler: AdaptivePollingScheduler) -> None:
    assert scheduler.current_tier("market-a") == "cool"
    assert scheduler.interval_seconds("market-a") == 60


@pytest.mark.unit
def test_volume_surge_promotes_cool_to_warm(
    scheduler: AdaptivePollingScheduler,
) -> None:
    scheduler.update_market_state(
        "market-a",
        volume_ratio_1h=1.6,
        has_active_signal=False,
        closes_in_seconds=100_000,
    )
    assert scheduler.current_tier("market-a") == "warm"


@pytest.mark.unit
def test_active_signal_promotes_warm_to_hot(
    scheduler: AdaptivePollingScheduler,
) -> None:
    # Drive up to warm first.
    scheduler.update_market_state(
        "market-a",
        volume_ratio_1h=1.6,
        has_active_signal=False,
        closes_in_seconds=100_000,
    )
    scheduler.update_market_state(
        "market-a",
        volume_ratio_1h=1.6,
        has_active_signal=True,
        closes_in_seconds=100_000,
    )
    assert scheduler.current_tier("market-a") == "hot"
    assert scheduler.interval_seconds("market-a") == 15


@pytest.mark.unit
def test_hysteresis_prevents_flap_near_warm_band(
    scheduler: AdaptivePollingScheduler,
) -> None:
    # Start in cool, promote to warm.
    scheduler.update_market_state(
        "market-a",
        volume_ratio_1h=1.6,
        has_active_signal=False,
        closes_in_seconds=100_000,
    )
    assert scheduler.current_tier("market-a") == "warm"
    # A value in the hysteresis band (between warm_demote=1.3 and
    # warm_promote=1.5) must not demote back to cool.
    scheduler.update_market_state(
        "market-a",
        volume_ratio_1h=1.4,
        has_active_signal=False,
        closes_in_seconds=100_000,
    )
    assert scheduler.current_tier("market-a") == "warm"


@pytest.mark.unit
def test_demote_path_from_hot_to_warm(
    scheduler: AdaptivePollingScheduler,
) -> None:
    scheduler._reset_market("market-a", "hot")
    scheduler.update_market_state(
        "market-a",
        volume_ratio_1h=1.5,
        has_active_signal=False,
        closes_in_seconds=100_000,
    )
    assert scheduler.current_tier("market-a") == "warm"


@pytest.mark.unit
def test_rate_limit_pressure_demotes_hot_market() -> None:
    body = PollingBody()
    sched = AdaptivePollingScheduler(body)
    sched.register("market-quiet", initial_tier="hot")
    sched.register("market-busy", initial_tier="hot")
    sched.update_market_state(
        "market-quiet",
        volume_ratio_1h=2.0,
        has_active_signal=True,
        closes_in_seconds=100_000,
    )
    sched.update_market_state(
        "market-busy",
        volume_ratio_1h=10.0,
        has_active_signal=True,
        closes_in_seconds=100_000,
    )
    sched.observe_platform_pressure("polymarket", utilization=0.92)
    # Quiet market (lower volume_ratio_1h) should be demoted first.
    assert sched.current_tier("market-quiet") == "warm"
    assert sched.current_tier("market-busy") == "hot"
    events = sched.drain_pressure_events()
    assert len(events) == 1
    assert events[0].platform == "polymarket"
    assert events[0].utilization == pytest.approx(0.92)


@pytest.mark.unit
def test_closes_within_24h_promotes_cool_to_warm(
    scheduler: AdaptivePollingScheduler,
) -> None:
    scheduler.update_market_state(
        "market-a",
        volume_ratio_1h=1.0,
        has_active_signal=False,
        closes_in_seconds=60_000,  # < 24h = 86400
    )
    assert scheduler.current_tier("market-a") == "warm"
