"""Factory that selects an EventBus implementation from `BusConfig`.

Call from the worker startup path:

    from augur_signals._config import load_config
    from augur_signals.bus._config import BusConfig
    from augur_signals.bus.factory import make_event_bus

    bus_config = load_config(Path("config/bus.toml"), BusConfig)
    bus = make_event_bus(bus_config)
    await bus.connect()

The monolith engine does not use this factory; it instantiates
`InProcessAsyncBus` directly with its native `MarketSignal`
interface. Phase 5 workers use the byte-level `EventBus` protocol
and select a backend via this factory at startup.
"""

from __future__ import annotations

from augur_signals.bus._config import BusConfig
from augur_signals.bus.base import BusError, EventBus
from augur_signals.bus.nats import NATSBus
from augur_signals.bus.redis_streams import RedisStreamsBus


def make_event_bus(config: BusConfig) -> EventBus:
    """Return an `EventBus` implementation selected by *config*.

    The `"memory"` variant of `BusConfig` is reserved for the
    monolith engine's in-process bus and is not served by this
    factory; callers that pass it receive `BusError` because they
    should reach for `InProcessAsyncBus` in `bus/memory.py`
    directly.
    """
    if config.backend.kind == "nats":
        return NATSBus(config.nats)
    if config.backend.kind == "redis":
        return RedisStreamsBus(config.redis)
    raise BusError(
        f"EventBus factory does not serve backend {config.backend.kind!r}; "
        "use InProcessAsyncBus for the single-process engine."
    )
