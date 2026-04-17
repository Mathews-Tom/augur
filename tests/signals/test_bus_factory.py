"""Tests for ``make_event_bus`` factory routing."""

from __future__ import annotations

import pytest

from augur_signals.bus._config import BackendBody, BusConfig, NATSBody, RedisBody
from augur_signals.bus.base import BusError
from augur_signals.bus.factory import make_event_bus
from augur_signals.bus.nats import NATSBus
from augur_signals.bus.redis_streams import RedisStreamsBus


@pytest.mark.unit
def test_factory_returns_nats_bus_for_nats_backend() -> None:
    cfg = BusConfig(
        backend=BackendBody(kind="nats"),
        nats=NATSBody(servers=["nats://example:4222"], stream_name="augur"),
    )
    bus = make_event_bus(cfg)
    assert isinstance(bus, NATSBus)


@pytest.mark.unit
def test_factory_returns_redis_bus_for_redis_backend() -> None:
    cfg = BusConfig(
        backend=BackendBody(kind="redis"),
        redis=RedisBody(url_env="REDIS_URL"),
    )
    bus = make_event_bus(cfg)
    assert isinstance(bus, RedisStreamsBus)


@pytest.mark.unit
def test_factory_rejects_memory_kind_with_clear_redirect() -> None:
    cfg = BusConfig(backend=BackendBody(kind="memory", capacity=64))
    with pytest.raises(BusError, match="InProcessAsyncBus"):
        make_event_bus(cfg)
