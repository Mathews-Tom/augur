"""TimescaleDB-backed persistence mirroring the DuckDBStore surface.

The adapter is a thin facade over `psycopg` that issues the same
schema statements the DuckDB store does, then converts the time-series
tables into TimescaleDB hypertables and attaches compression and
retention policies. Every public method has a matching method on
`DuckDBStore` so engine code flips backends via configuration without
call-site edits.

The connection is injected so unit tests can swap in fakes or
sqlite-backed shims. Production startup reads the DSN from the env var
named in `storage.toml`; the adapter itself does not know about the
filesystem.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from augur_signals.models import (
    FeatureVector,
    ManipulationFlag,
    MarketSignal,
    MarketSnapshot,
)
from augur_signals.storage._config import (
    CompressionBody,
    HypertableBody,
    RetentionBody,
)

if TYPE_CHECKING:
    from psycopg import AsyncConnection


_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        market_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL,
        last_price DOUBLE PRECISION,
        bid DOUBLE PRECISION,
        ask DOUBLE PRECISION,
        spread DOUBLE PRECISION,
        volume_24h DOUBLE PRECISION,
        liquidity DOUBLE PRECISION,
        question TEXT,
        resolution_source TEXT,
        resolution_criteria TEXT,
        closes_at TIMESTAMPTZ,
        raw_json JSONB,
        schema_version TEXT NOT NULL,
        PRIMARY KEY (market_id, platform, timestamp)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS features (
        market_id TEXT NOT NULL,
        computed_at TIMESTAMPTZ NOT NULL,
        payload JSONB NOT NULL,
        schema_version TEXT NOT NULL,
        PRIMARY KEY (market_id, computed_at)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
        signal_id TEXT PRIMARY KEY,
        market_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        magnitude DOUBLE PRECISION NOT NULL,
        direction INTEGER NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,
        fdr_adjusted BOOLEAN NOT NULL,
        detected_at TIMESTAMPTZ NOT NULL,
        window_seconds INTEGER NOT NULL,
        liquidity_tier TEXT NOT NULL,
        related_market_ids TEXT[],
        raw_features JSONB NOT NULL,
        schema_version TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS manipulation_flags (
        signal_id TEXT NOT NULL,
        flag TEXT NOT NULL,
        detected_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (signal_id, flag)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS calibration_fpr (
        detector_id TEXT NOT NULL,
        market_id TEXT NOT NULL,
        fpr DOUBLE PRECISION NOT NULL,
        sample_size INTEGER NOT NULL,
        computed_at TIMESTAMPTZ NOT NULL,
        label_protocol_version TEXT NOT NULL,
        PRIMARY KEY (detector_id, market_id, computed_at)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reliability_curves (
        detector_id TEXT NOT NULL,
        liquidity_tier TEXT NOT NULL,
        curve_version TEXT NOT NULL,
        deciles JSONB NOT NULL,
        built_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (detector_id, liquidity_tier, curve_version)
    );
    """,
)


@dataclass(frozen=True, slots=True)
class HypertableSpec:
    """One hypertable's partition/compression/retention policy."""

    table: str
    time_column: str
    chunk_interval_days: int
    segment_by: str | None = None
    compress_after_days: int = 0
    retention_days: int = 0


class TimescaleDBStore:
    """Async TimescaleDB adapter mirroring DuckDBStore's method surface.

    Attributes:
        CURRENT_SCHEMA_VERSION: Integer version stamped into the
            `schema_version` table after `initialize` applies all
            pending migrations.
    """

    CURRENT_SCHEMA_VERSION: int = 1

    def __init__(
        self,
        connection: AsyncConnection[Any],
        *,
        hypertable: HypertableBody,
        retention: RetentionBody,
        compression: CompressionBody,
    ) -> None:
        self._conn = connection
        self._hypertable = hypertable
        self._retention = retention
        self._compression = compression

    def hypertable_specs(self) -> list[HypertableSpec]:
        """Return the hypertable policies derived from configuration."""
        return [
            HypertableSpec(
                table="snapshots",
                time_column="timestamp",
                chunk_interval_days=self._hypertable.snapshot_chunk_interval_days,
                segment_by="market_id, platform",
                compress_after_days=self._compression.snapshot_compress_after_days,
                retention_days=self._retention.snapshot_retention_days,
            ),
            HypertableSpec(
                table="features",
                time_column="computed_at",
                chunk_interval_days=self._hypertable.feature_chunk_interval_days,
                compress_after_days=self._compression.feature_compress_after_days,
                retention_days=self._retention.feature_retention_days,
            ),
            HypertableSpec(
                table="signals",
                time_column="detected_at",
                chunk_interval_days=self._hypertable.signal_chunk_interval_days,
                compress_after_days=self._compression.signal_compress_after_days,
                retention_days=self._retention.signal_retention_days,
            ),
        ]

    async def initialize(self) -> None:
        """Apply migrations, create hypertables, attach policies."""
        async with self._conn.cursor() as cur:
            for stmt in _SCHEMA_STATEMENTS:
                await cur.execute(stmt)
            for spec in self.hypertable_specs():
                await cur.execute(
                    """
                    SELECT create_hypertable(
                        %s, %s,
                        chunk_time_interval => make_interval(days => %s),
                        if_not_exists => TRUE
                    )
                    """,
                    [spec.table, spec.time_column, spec.chunk_interval_days],
                )
                if spec.compress_after_days > 0:
                    if spec.segment_by:
                        await cur.execute(
                            "ALTER TABLE "
                            + self._quote_ident(spec.table)
                            + " SET (timescaledb.compress, "
                            "timescaledb.compress_segmentby = %s)",
                            [spec.segment_by],
                        )
                    await cur.execute(
                        """
                        SELECT add_compression_policy(
                            %s, make_interval(days => %s),
                            if_not_exists => TRUE
                        )
                        """,
                        [spec.table, spec.compress_after_days],
                    )
                if spec.retention_days > 0:
                    await cur.execute(
                        """
                        SELECT add_retention_policy(
                            %s, make_interval(days => %s),
                            if_not_exists => TRUE
                        )
                        """,
                        [spec.table, spec.retention_days],
                    )
            await cur.execute(
                """
                INSERT INTO schema_version (version, applied_at)
                VALUES (%s, now())
                ON CONFLICT (version) DO NOTHING
                """,
                [self.CURRENT_SCHEMA_VERSION],
            )
        await self._conn.commit()

    # --- writes ---------------------------------------------------------

    async def insert_snapshot(self, snapshot: MarketSnapshot) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO snapshots (
                    market_id, platform, timestamp, last_price, bid, ask,
                    spread, volume_24h, liquidity, question,
                    resolution_source, resolution_criteria, closes_at,
                    raw_json, schema_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (market_id, platform, timestamp) DO UPDATE SET
                    last_price = EXCLUDED.last_price,
                    bid = EXCLUDED.bid,
                    ask = EXCLUDED.ask,
                    spread = EXCLUDED.spread,
                    volume_24h = EXCLUDED.volume_24h,
                    liquidity = EXCLUDED.liquidity,
                    question = EXCLUDED.question,
                    resolution_source = EXCLUDED.resolution_source,
                    resolution_criteria = EXCLUDED.resolution_criteria,
                    closes_at = EXCLUDED.closes_at,
                    raw_json = EXCLUDED.raw_json,
                    schema_version = EXCLUDED.schema_version
                """,
                [
                    snapshot.market_id,
                    snapshot.platform,
                    snapshot.timestamp,
                    snapshot.last_price,
                    snapshot.bid,
                    snapshot.ask,
                    snapshot.spread,
                    snapshot.volume_24h,
                    snapshot.liquidity,
                    snapshot.question,
                    snapshot.resolution_source,
                    snapshot.resolution_criteria,
                    snapshot.closes_at,
                    json.dumps(snapshot.raw_json),
                    snapshot.schema_version,
                ],
            )
        await self._conn.commit()

    async def insert_feature(self, feature: FeatureVector) -> None:
        payload = feature.model_dump(mode="json", exclude={"market_id", "computed_at"})
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO features (market_id, computed_at, payload, schema_version)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT (market_id, computed_at) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    schema_version = EXCLUDED.schema_version
                """,
                [
                    feature.market_id,
                    feature.computed_at,
                    json.dumps(payload),
                    feature.schema_version,
                ],
            )
        await self._conn.commit()

    async def insert_signal(self, signal: MarketSignal) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO signals (
                    signal_id, market_id, platform, signal_type, magnitude,
                    direction, confidence, fdr_adjusted, detected_at,
                    window_seconds, liquidity_tier, related_market_ids,
                    raw_features, schema_version
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                )
                ON CONFLICT (signal_id) DO UPDATE SET
                    magnitude = EXCLUDED.magnitude,
                    direction = EXCLUDED.direction,
                    confidence = EXCLUDED.confidence,
                    fdr_adjusted = EXCLUDED.fdr_adjusted,
                    detected_at = EXCLUDED.detected_at,
                    window_seconds = EXCLUDED.window_seconds,
                    liquidity_tier = EXCLUDED.liquidity_tier,
                    related_market_ids = EXCLUDED.related_market_ids,
                    raw_features = EXCLUDED.raw_features,
                    schema_version = EXCLUDED.schema_version
                """,
                [
                    signal.signal_id,
                    signal.market_id,
                    signal.platform,
                    signal.signal_type.value,
                    signal.magnitude,
                    signal.direction,
                    signal.confidence,
                    signal.fdr_adjusted,
                    signal.detected_at,
                    signal.window_seconds,
                    signal.liquidity_tier,
                    list(signal.related_market_ids),
                    json.dumps(signal.raw_features),
                    signal.schema_version,
                ],
            )
        await self._conn.commit()
        if signal.manipulation_flags:
            await self.insert_manipulation_flags(
                signal.signal_id,
                signal.detected_at,
                signal.manipulation_flags,
            )

    async def insert_manipulation_flags(
        self,
        signal_id: str,
        detected_at: datetime,
        flags: Iterable[ManipulationFlag],
    ) -> None:
        async with self._conn.cursor() as cur:
            for flag in flags:
                await cur.execute(
                    """
                    INSERT INTO manipulation_flags (signal_id, flag, detected_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (signal_id, flag) DO UPDATE SET
                        detected_at = EXCLUDED.detected_at
                    """,
                    [signal_id, flag.value, detected_at],
                )
        await self._conn.commit()

    # --- reads ----------------------------------------------------------

    async def latest_snapshot(self, market_id: str) -> MarketSnapshot | None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM snapshots WHERE market_id = %s ORDER BY timestamp DESC LIMIT 1",
                [market_id],
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return _row_to_snapshot(row)

    async def snapshots_in_window(
        self,
        market_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[MarketSnapshot]:
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM snapshots
                WHERE market_id = %s AND timestamp BETWEEN %s AND %s
                ORDER BY timestamp ASC
                """,
                [market_id, window_start, window_end],
            )
            rows = await cur.fetchall()
        return [_row_to_snapshot(row) for row in rows]

    async def signals_in_window(
        self,
        market_ids: Sequence[str],
        window_start: datetime,
        window_end: datetime,
    ) -> list[MarketSignal]:
        if not market_ids:
            return []
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM signals
                WHERE market_id = ANY(%s) AND detected_at BETWEEN %s AND %s
                ORDER BY detected_at ASC
                """,
                [list(market_ids), window_start, window_end],
            )
            rows = await cur.fetchall()
            signals = [_row_to_signal(row) for row in rows]
            if not signals:
                return signals
            signal_ids = [s.signal_id for s in signals]
            await cur.execute(
                "SELECT signal_id, flag FROM manipulation_flags WHERE signal_id = ANY(%s)",
                [signal_ids],
            )
            flag_rows = await cur.fetchall()
        flags_by_signal: dict[str, list[ManipulationFlag]] = {}
        for signal_id, flag_value in flag_rows:
            flags_by_signal.setdefault(signal_id, []).append(ManipulationFlag(flag_value))
        return [
            signal.model_copy(
                update={"manipulation_flags": flags_by_signal.get(signal.signal_id, [])}
            )
            for signal in signals
        ]

    # --- lifecycle ------------------------------------------------------

    async def close(self) -> None:
        await self._conn.close()

    @staticmethod
    def _quote_ident(identifier: str) -> str:
        """Quote a SQL identifier rejecting anything outside [a-z0-9_]."""
        if not identifier or not all(c.isalnum() or c == "_" for c in identifier):
            raise ValueError(f"Refusing to quote identifier: {identifier!r}")
        return f'"{identifier}"'


def _row_to_snapshot(row: tuple[Any, ...]) -> MarketSnapshot:
    (
        market_id,
        platform,
        timestamp,
        last_price,
        bid,
        ask,
        spread,
        volume_24h,
        liquidity,
        question,
        resolution_source,
        resolution_criteria,
        closes_at,
        raw_json,
        schema_version,
    ) = row
    return MarketSnapshot.model_validate(
        {
            "market_id": market_id,
            "platform": platform,
            "timestamp": timestamp,
            "last_price": last_price,
            "bid": bid,
            "ask": ask,
            "spread": spread,
            "volume_24h": volume_24h,
            "liquidity": liquidity,
            "question": question,
            "resolution_source": resolution_source,
            "resolution_criteria": resolution_criteria,
            "closes_at": closes_at,
            "raw_json": json.loads(raw_json) if isinstance(raw_json, str) else raw_json,
            "schema_version": schema_version,
        }
    )


def _row_to_signal(row: tuple[Any, ...]) -> MarketSignal:
    (
        signal_id,
        market_id,
        platform,
        signal_type,
        magnitude,
        direction,
        confidence,
        fdr_adjusted,
        detected_at,
        window_seconds,
        liquidity_tier,
        related_market_ids,
        raw_features,
        schema_version,
    ) = row
    return MarketSignal.model_validate(
        {
            "signal_id": signal_id,
            "market_id": market_id,
            "platform": platform,
            "signal_type": signal_type,
            "magnitude": magnitude,
            "direction": direction,
            "confidence": confidence,
            "fdr_adjusted": fdr_adjusted,
            "detected_at": detected_at,
            "window_seconds": window_seconds,
            "liquidity_tier": liquidity_tier,
            "related_market_ids": list(related_market_ids or []),
            "raw_features": (
                json.loads(raw_features) if isinstance(raw_features, str) else raw_features
            ),
            "schema_version": schema_version,
        }
    )
