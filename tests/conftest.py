"""Session-scoped test fixtures shared across the three subpackage trees."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _configure_logging_for_tests() -> None:
    """Initialize structlog once per session at WARNING.

    Individual tests that exercise logging output reconfigure to the
    level they need via `augur_signals._logging.configure_logging`.
    """
    from augur_signals._logging import configure_logging

    configure_logging(level="WARNING")


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Per-test temporary data directory under pytest's tmp_path."""
    directory = tmp_path / "augur_data"
    directory.mkdir()
    return directory
