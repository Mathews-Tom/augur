"""Storage backend factory keyed by `StorageConfig.backend.kind`.

The Phase 1-4 monolith calls `make_duckdb_store(config)` directly
when instantiating the engine. Phase 5 workers use this factory at
startup so flipping `config/storage.toml` `backend.kind` from
`"duckdb"` to `"timescaledb"` restarts the process against the
new backend without code edits.

`make_storage` returns the DuckDB adapter synchronously or the
TimescaleDB adapter paired with an open `AsyncConnection`; the
TimescaleDB branch is `async` because opening the connection is
awaited. Callers select the right helper for their deployment mode.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from augur_signals.storage._config import StorageConfig
from augur_signals.storage.duckdb_store import DuckDBStore
from augur_signals.storage.timescaledb_store import TimescaleDBStore

if TYPE_CHECKING:
    from psycopg import AsyncConnection


class StorageConfigurationError(RuntimeError):
    """Raised for malformed or inconsistent storage configuration."""


def make_duckdb_store(config: StorageConfig) -> DuckDBStore:
    """Open the Phase 1-4 DuckDB store from *config*."""
    if config.backend.kind != "duckdb":
        raise StorageConfigurationError(
            f"make_duckdb_store called with backend.kind = {config.backend.kind!r}"
        )
    return DuckDBStore(Path(config.backend.duckdb_path))


async def make_timescaledb_store(
    config: StorageConfig, *, connection: AsyncConnection[object] | None = None
) -> TimescaleDBStore:
    """Open a TimescaleDB store from *config*.

    If *connection* is None the factory reads the DSN from the env var
    named in `config.backend.timescale_url_env` and opens a new
    `AsyncConnection`. Tests pass a stub connection explicitly.
    """
    if config.backend.kind != "timescaledb":
        raise StorageConfigurationError(
            f"make_timescaledb_store called with backend.kind = {config.backend.kind!r}"
        )
    if connection is None:
        import psycopg

        dsn = os.environ[config.backend.timescale_url_env]
        connection = await psycopg.AsyncConnection.connect(dsn)
    return TimescaleDBStore(
        connection,
        hypertable=config.hypertable,
        retention=config.retention,
        compression=config.compression,
    )
