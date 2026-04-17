"""Structured JSON logging for the Augur engine.

All logs serialize to single-line JSON and write to stdout. A downstream
log shipper routes stdout into the centralized store once the
multi-process runtime is operational. Module callers obtain bound
loggers via `get_logger(__name__)` and add per-request or per-signal
context with `structlog.contextvars.bind_contextvars`.

Conventions
-----------
- Log keys are snake_case.
- Every entry carries `signal_id` and `market_id` when available,
  bound via `bind_contextvars` at the point where the identity is
  established.
- Log values never contain PII or secrets.
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.stdlib import BoundLogger


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to emit UTC-stamped JSON records to stdout.

    Idempotent across calls that precede any `get_logger` invocation
    on the process. Because structlog caches the wrapper class on first
    logger retrieval, a call to `configure_logging` that follows an
    earlier `get_logger` affects subsequent loggers only; previously
    returned loggers retain their original filtering level. Production
    code configures once at engine startup before any module-level
    `get_logger` runs; tests that change the level re-retrieve their
    logger after reconfiguring.
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
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> BoundLogger:
    """Return a bound logger for *name*. Call once per module.

    Structlog's own `get_logger` is typed `Any` because the concrete
    wrapper depends on the configured `wrapper_class`. This wrapper
    casts to the stdlib-compatible `BoundLogger` so call sites get
    typed method access.
    """
    return cast(BoundLogger, structlog.get_logger(name))
