"""Tests for the structured logging setup."""

from __future__ import annotations

import json
from io import StringIO

import pytest

from augur_signals._logging import configure_logging, get_logger


@pytest.mark.unit
def test_configure_logging_emits_json(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    configure_logging(level="INFO")
    logger = get_logger("test.module")
    logger.info("example_event", market_id="market-123", count=7)

    line = buffer.getvalue().strip()
    record = json.loads(line)
    assert record["event"] == "example_event"
    assert record["market_id"] == "market-123"
    assert record["count"] == 7
    assert record["level"] == "info"
    assert "timestamp" in record


@pytest.mark.unit
def test_get_logger_returns_usable_logger() -> None:
    configure_logging(level="INFO")
    logger = get_logger("any.module")
    assert hasattr(logger, "info")
    assert hasattr(logger, "warning")
    assert hasattr(logger, "error")


@pytest.mark.unit
def test_configure_logging_filters_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = StringIO()
    monkeypatch.setattr("sys.stdout", buffer)

    configure_logging(level="WARNING")
    logger = get_logger("test.module")
    logger.info("filtered_out")
    logger.warning("kept")

    emitted = [ln for ln in buffer.getvalue().splitlines() if ln]
    assert len(emitted) == 1
    assert json.loads(emitted[0])["event"] == "kept"
