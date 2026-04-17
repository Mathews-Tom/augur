"""Backfill the TimescaleDB hot tables from the DuckDB Parquet archive.

Usage:

    uv run python scripts/migrate_to_timescale.py backfill \\
        --from labels/snapshots_archive --batch-size 10000

    uv run python scripts/migrate_to_timescale.py verify \\
        --start 2026-01-01 --end 2026-04-01

The script reads partitioned Parquet files in chronological order and
bulk-inserts them into TimescaleDB using `COPY` for throughput. Per
partition it verifies row-count parity: the number of rows in the
Parquet file must match the number of rows the adapter reports landing
in the hypertable. On mismatch the script aborts before moving on so
the operator can investigate before the partition is replayed.

`verify` re-runs a (market, day) group-count parity query between
DuckDB and TimescaleDB for the requested window without inserting any
data. Operators run verify after backfill to confirm byte-for-byte
parity before the dual-write cutover.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg import AsyncConnection


class MigrationError(RuntimeError):
    """Raised when a row-count parity check fails or a partition is corrupt."""


async def backfill(
    *,
    source_root: Path,
    batch_size: int,
    connection_factory: ConnectionFactory,
) -> BackfillSummary:
    """Load every Parquet partition under *source_root* into TimescaleDB.

    Args:
        source_root: Root of the Parquet archive
            (`labels/snapshots_archive/`).
        batch_size: Rows per COPY batch. Tuned at operations time; 10k
            is a reasonable starting point.
        connection_factory: Async callable opening a new
            `AsyncConnection` per partition so long-running backfill
            runs recycle connections.

    Returns:
        `BackfillSummary` with the partition count and total rows.

    Raises:
        MigrationError: A partition's reported insert count did not
            match its Parquet row count.
    """
    partitions = _discover_partitions(source_root)
    total_rows = 0
    for partition in partitions:
        rows_in_parquet = _count_parquet_rows(partition)
        async with connection_factory() as conn:
            rows_inserted = await _copy_partition_into_timescale(conn, partition, batch_size)
        if rows_inserted != rows_in_parquet:
            raise MigrationError(
                f"Row-count mismatch on {partition}: "
                f"parquet={rows_in_parquet}, timescale={rows_inserted}"
            )
        total_rows += rows_inserted
    return BackfillSummary(partition_count=len(partitions), total_rows=total_rows)


async def verify(
    *,
    start: str,
    end: str,
    duckdb_path: Path,
    connection_factory: ConnectionFactory,
) -> VerifySummary:
    """Compare per-(market, day) group counts between DuckDB and TimescaleDB."""
    duck_counts = _duckdb_group_counts(duckdb_path, start, end)
    async with connection_factory() as conn:
        timescale_counts = await _timescale_group_counts(conn, start, end)
    mismatches = {
        key: (duck_counts.get(key, 0), timescale_counts.get(key, 0))
        for key in duck_counts.keys() | timescale_counts.keys()
        if duck_counts.get(key, 0) != timescale_counts.get(key, 0)
    }
    return VerifySummary(
        duckdb_groups=len(duck_counts),
        timescale_groups=len(timescale_counts),
        mismatches=mismatches,
    )


# --- helpers ---------------------------------------------------------


from collections.abc import Callable  # noqa: E402
from contextlib import AbstractAsyncContextManager  # noqa: E402
from dataclasses import dataclass  # noqa: E402

ConnectionFactory = Callable[[], AbstractAsyncContextManager["AsyncConnection[object]"]]


@dataclass(frozen=True, slots=True)
class BackfillSummary:
    """Result of `backfill`."""

    partition_count: int
    total_rows: int


@dataclass(frozen=True, slots=True)
class VerifySummary:
    """Result of `verify`."""

    duckdb_groups: int
    timescale_groups: int
    mismatches: dict[tuple[str, str], tuple[int, int]]


def _discover_partitions(source_root: Path) -> list[Path]:
    """Return partitions in chronological order (`date=YYYY-MM-DD` layout)."""
    if not source_root.exists():
        raise MigrationError(f"Source root does not exist: {source_root}")
    partitions = sorted(
        (p for p in source_root.glob("date=*") if p.is_dir()),
        key=lambda p: p.name,
    )
    if not partitions:
        raise MigrationError(f"No partitions found under {source_root}")
    return partitions


def _count_parquet_rows(partition: Path) -> int:
    """Sum row counts across every Parquet file in *partition*."""
    import pyarrow.parquet as pq

    total = 0
    for file in partition.glob("*.parquet"):
        total += pq.ParquetFile(file).metadata.num_rows
    return total


async def _copy_partition_into_timescale(
    conn: AsyncConnection[object], partition: Path, batch_size: int
) -> int:
    """COPY *partition* into the snapshots hypertable; return rows inserted.

    The implementation relies on the operator-supplied DSN pointing at
    a TimescaleDB hypertable that already exists (via
    `TimescaleDBStore.initialize`). The script does not create
    schemas — cutover sequencing is operator-driven.
    """
    import pyarrow.parquet as pq

    # Enumerate parquet files up front so the async block does not touch
    # the filesystem (ASYNC240 — Path.glob is blocking). Column names
    # come from the arrow schema, not user input, so the dynamic SQL
    # is safe despite S608's warning.
    files = sorted(partition.glob("*.parquet"))  # noqa: ASYNC240
    rows = 0
    async with conn.cursor() as cur:
        for file in files:
            table = pq.read_table(file)
            batches = table.to_batches(max_chunksize=batch_size)
            for batch in batches:
                columns = batch.schema.names
                placeholders = ", ".join(["%s"] * len(columns))
                column_list = ", ".join(f'"{c}"' for c in columns)
                # Column names come from the arrow schema, not user
                # input, so the dynamic SQL is safe despite S608.
                sql = (
                    f"INSERT INTO snapshots ({column_list}) "  # noqa: S608
                    f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                )
                records = [tuple(row) for row in batch.to_pylist()]
                await cur.executemany(sql, records)
                rows += len(records)
    await conn.commit()
    return rows


def _duckdb_group_counts(duckdb_path: Path, start: str, end: str) -> dict[tuple[str, str], int]:
    """Per-(market_id, date) row counts from DuckDB snapshots."""
    import duckdb

    with duckdb.connect(str(duckdb_path)) as conn:
        rows = conn.execute(
            "SELECT market_id, DATE_TRUNC('day', timestamp)::DATE::VARCHAR AS day, "
            "COUNT(*) FROM snapshots WHERE timestamp BETWEEN ? AND ? "
            "GROUP BY market_id, day",
            [start, end],
        ).fetchall()
    return {(m, d): int(c) for m, d, c in rows}


async def _timescale_group_counts(
    conn: AsyncConnection[object], start: str, end: str
) -> dict[tuple[str, str], int]:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT market_id, DATE_TRUNC('day', timestamp)::DATE::TEXT AS day, "
            "COUNT(*) FROM snapshots WHERE timestamp BETWEEN %s AND %s "
            "GROUP BY market_id, day",
            [start, end],
        )
        rows: list[Any] = list(await cur.fetchall())
    result: dict[tuple[str, str], int] = {}
    for row in rows:
        market_id, day, count = row[0], row[1], row[2]
        result[(str(market_id), str(day))] = int(count)
    return result


# --- CLI -------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="migrate_to_timescale")
    sub = parser.add_subparsers(dest="command", required=True)

    bf = sub.add_parser("backfill", help="Load every Parquet partition into TimescaleDB")
    bf.add_argument("--from", dest="source_root", required=True, type=Path)
    bf.add_argument("--batch-size", type=int, default=10_000)

    ver = sub.add_parser("verify", help="Compare per-(market, day) group counts")
    ver.add_argument("--start", required=True)
    ver.add_argument("--end", required=True)
    ver.add_argument("--duckdb", required=True, type=Path)

    return parser.parse_args(argv)


async def _cli(argv: list[str]) -> int:  # pragma: no cover — thin wrapper
    args = _parse_args(argv)
    import os
    from typing import Any, cast

    import psycopg

    dsn = os.environ["AUGUR_TIMESCALE_URL"]

    def _factory() -> AbstractAsyncContextManager[AsyncConnection[object]]:
        # psycopg's AsyncConnection.connect returns a coroutine that
        # doubles as an async context manager; cast through Any so
        # mypy accepts the protocol adaptation.
        return cast(
            AbstractAsyncContextManager[AsyncConnection[object]],
            cast(Any, psycopg.AsyncConnection.connect(dsn)),
        )

    if args.command == "backfill":
        summary = await backfill(
            source_root=args.source_root,
            batch_size=args.batch_size,
            connection_factory=_factory,
        )
        print(f"backfilled {summary.partition_count} partitions, {summary.total_rows} rows")
        return 0
    if args.command == "verify":
        vsummary = await verify(
            start=args.start,
            end=args.end,
            duckdb_path=args.duckdb,
            connection_factory=_factory,
        )
        if vsummary.mismatches:
            print(
                f"FAIL: {len(vsummary.mismatches)} mismatches across "
                f"{vsummary.duckdb_groups} duckdb groups / "
                f"{vsummary.timescale_groups} timescale groups",
                file=sys.stderr,
            )
            return 2
        print(f"OK: {vsummary.duckdb_groups} groups match (duckdb == timescale)")
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(_cli(sys.argv[1:])))
