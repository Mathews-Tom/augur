"""Tests for the WebSocket broadcaster and frame helpers."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from augur_format.transport.websocket import (
    FrameType,
    HeartbeatScheduler,
    WebSocketBroadcaster,
    heartbeat_frame,
    signal_frame,
    storm_end_frame,
    storm_start_frame,
)
from augur_signals.models import (
    InterpretationMode,
    MarketSignal,
    SignalContext,
    SignalType,
    new_signal_id,
)


def _context() -> SignalContext:
    signal = MarketSignal(
        signal_id=new_signal_id(),
        market_id="kalshi_fed",
        platform="kalshi",
        signal_type=SignalType.PRICE_VELOCITY,
        magnitude=0.8,
        direction=1,
        confidence=0.7,
        fdr_adjusted=True,
        detected_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        window_seconds=300,
        liquidity_tier="high",
        raw_features={"calibration_provenance": "d@identity_v0"},
    )
    return SignalContext(
        signal=signal,
        market_question="q",
        resolution_criteria="c",
        resolution_source="s",
        closes_at=datetime(2026, 6, 15, tzinfo=UTC),
        related_markets=[],
        investigation_prompts=[],
        interpretation_mode=InterpretationMode.DETERMINISTIC,
    )


@pytest.mark.unit
def test_signal_frame_payload_contains_canonical_signal_context() -> None:
    ctx = _context()
    frame = signal_frame(ctx, datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    assert frame.frame_type == FrameType.SIGNAL
    assert frame.payload is not None
    assert frame.payload["signal"]["signal_id"] == ctx.signal.signal_id


@pytest.mark.unit
def test_heartbeat_frame_has_no_payload() -> None:
    frame = heartbeat_frame(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    assert frame.frame_type == FrameType.HEARTBEAT
    assert frame.payload is None


@pytest.mark.unit
def test_storm_frames_emit_expected_types() -> None:
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    assert storm_start_frame(now).frame_type == FrameType.STORM_START
    assert storm_end_frame(now).frame_type == FrameType.STORM_END


@pytest.mark.unit
def test_frame_to_json_uses_z_suffix() -> None:
    frame = heartbeat_frame(datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    body = json.loads(frame.to_json())
    assert body["ts"].endswith("Z")
    assert "payload" not in body


@pytest.mark.asyncio
async def test_broadcaster_fans_out_to_subscribers() -> None:
    broadcaster = WebSocketBroadcaster(per_connection_buffer=8)
    sub = broadcaster.subscribe()
    await broadcaster.publish(heartbeat_frame(datetime(2026, 3, 15, tzinfo=UTC)))
    frame = await asyncio.wait_for(sub.queue.get(), timeout=0.1)
    assert frame.frame_type == FrameType.HEARTBEAT


@pytest.mark.asyncio
async def test_broadcaster_filters_by_consumer_type() -> None:
    broadcaster = WebSocketBroadcaster(per_connection_buffer=4)
    dashboard = broadcaster.subscribe(consumer_type="dashboard")
    macro = broadcaster.subscribe(consumer_type="macro_research_agent")
    frame = heartbeat_frame(datetime(2026, 3, 15, tzinfo=UTC))
    await broadcaster.publish(
        frame,
        consumer_type_filter=lambda ct: ct == "dashboard",
    )
    assert dashboard.queue.qsize() == 1
    assert macro.queue.qsize() == 0


@pytest.mark.asyncio
async def test_broadcaster_drops_oldest_on_full_queue() -> None:
    broadcaster = WebSocketBroadcaster(per_connection_buffer=2)
    sub = broadcaster.subscribe()
    now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    for _ in range(5):
        await broadcaster.publish(heartbeat_frame(now))
    # Queue holds only the last 2; dropped counter tracks the overflow.
    assert sub.queue.qsize() == 2
    assert sub.dropped >= 3


@pytest.mark.unit
def test_heartbeat_scheduler_emits_after_interval() -> None:
    scheduler = HeartbeatScheduler(interval_seconds=30)
    t0 = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    assert scheduler.should_emit(t0)
    scheduler.record(t0)
    assert not scheduler.should_emit(t0 + timedelta(seconds=10))
    assert scheduler.should_emit(t0 + timedelta(seconds=30))


@pytest.mark.unit
def test_broadcaster_rejects_invalid_buffer() -> None:
    with pytest.raises(ValueError, match="positive"):
        WebSocketBroadcaster(per_connection_buffer=0)
