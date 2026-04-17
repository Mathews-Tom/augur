"""Structured JSON logging for the Augur engine.

All logs serialize to single-line JSON and write to stdout. A downstream
log shipper routes stdout into the centralized store once the
multi-process runtime is operational. Module callers obtain bound
loggers via ``get_logger(__name__)`` and add per-request or per-signal
context with ``structlog.contextvars.bind_contextvars``.

Conventions
-----------
- Log keys are snake_case.
- Every entry carries ``signal_id`` and ``market_id`` when available,
  bound via ``bind_contextvars`` at the point where the identity is
  established.
- Log values never contain PII or secrets.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to emit UTC-stamped JSON records to stdout.

    Idempotent: safe to call multiple times from a single process. The
    filtering level maps the textual level through the standard logging
    module's ``getLevelName`` so callers can pass "INFO", "DEBUG", etc.
    """
    level_number = logging.getLevelNamesMapping()[level]
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_number),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return a bound logger for *name*. Call once per module.

    The return type is intentionally untyped because structlog does not
    ship first-party stubs and the concrete wrapper class depends on
    the filtering level configured at runtime. Callers interact with
    the logger via the standard ``info``, ``warning``, ``error`` methods.
    """
    return structlog.get_logger(name)
