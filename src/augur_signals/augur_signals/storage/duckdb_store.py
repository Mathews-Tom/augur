"""DuckDB-backed persistence for snapshots, features, signals, and calibration state.

Schema mirrors docs/architecture/system-design.md §Storage Schema.
Migrations are version-numbered and idempotent; the `initialize`
method advances the `schema_version` table and applies pending
migrations in order.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from augur_signals.models import (
    FeatureVector,
    ManipulationFlag,
    MarketSignal,
    MarketSnapshot,
)

_SCHEMA_V1 = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        market_id VARCHAR NOT NULL,
        platform VARCHAR NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        last_price DOUBLE,
        bid DOUBLE,
        ask DOUBLE,
        spread DOUBLE,
        volume_24h DOUBLE,
        liquidity DOUBLE,
        question VARCHAR,
        resolution_source VARCHAR,
        resolution_criteria VARCHAR,
        closes_at TIMESTAMP,
        raw_json JSON,
        schema_version VARCHAR NOT NULL,
        PRIMARY KEY (market_id, platform, timestamp)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS features (
        market_id VARCHAR NOT NULL,
        computed_at TIMESTAMP NOT NULL,
        payload JSON NOT NULL,
        schema_version VARCHAR NOT NULL,
        PRIMARY KEY (market_id, computed_at)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
        signal_id VARCHAR PRIMARY KEY,
        market_id VARCHAR NOT NULL,
        platform VARCHAR NOT NULL,
        signal_type VARCHAR NOT NULL,
        magnitude DOUBLE NOT NULL,
        direction INTEGER NOT NULL,
        confidence DOUBLE NOT NULL,
        fdr_adjusted BOOLEAN NOT NULL,
        detected_at TIMESTAMP NOT NULL,
        window_seconds INTEGER NOT NULL,
        liquidity_tier VARCHAR NOT NULL,
        related_market_ids VARCHAR[],
        raw_features JSON NOT NULL,
        schema_version VARCHAR NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS manipulation_flags (
        signal_id VARCHAR NOT NULL,
        flag VARCHAR NOT NULL,
        detected_at TIMESTAMP NOT NULL,
        PRIMARY KEY (signal_id, flag)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS calibration_fpr (
        detector_id VARCHAR NOT NULL,
        market_id VARCHAR NOT NULL,
        fpr DOUBLE NOT NULL,
        sample_size INTEGER NOT NULL,
        computed_at TIMESTAMP NOT NULL,
        label_protocol_version VARCHAR NOT NULL,
        PRIMARY KEY (detector_id, market_id, computed_at)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reliability_curves (
        detector_id VARCHAR NOT NULL,
        liquidity_tier VARCHAR NOT NULL,
        curve_version VARCHAR NOT NULL,
        deciles JSON NOT NULL,
        built_at TIMESTAMP NOT NULL,
        PRIMARY KEY (detector_id, liquidity_tier, curve_version)
    );
    """,
)


class DuckDBStore:
    """Thin synchronous facade over a DuckDB connection.

    The engine serializes storage calls so a single connection is safe.
    The multi-process runtime replaces this with the TimescaleDB
    adapter; every public method here has a matching method on the
    later adapter so call sites do not change.
    """

    CURRENT_SCHEMA_VERSION: int = 1

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(path))

    def initialize(self) -> None:
        """Apply all pending migrations."""
        for statement in _SCHEMA_V1:
            self._conn.execute(statement)
        self._conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            [self.CURRENT_SCHEMA_VERSION, datetime.now().astimezone()],
        )

    # --- writes ---------------------------------------------------------

    def insert_snapshot(self, snapshot: MarketSnapshot) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO snapshots VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
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

    def insert_feature(self, feature: FeatureVector) -> None:
        payload = feature.model_dump(mode="json", exclude={"market_id", "computed_at"})
        self._conn.execute(
            "INSERT OR REPLACE INTO features VALUES (?, ?, ?, ?)",
            [
                feature.market_id,
                feature.computed_at,
                json.dumps(payload),
                feature.schema_version,
            ],
        )

    def insert_signal(self, signal: MarketSignal) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO signals VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
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
        if signal.manipulation_flags:
            self.insert_manipulation_flags(
                signal.signal_id,
                signal.detected_at,
                signal.manipulation_flags,
            )

    def insert_manipulation_flags(
        self,
        signal_id: str,
        detected_at: datetime,
        flags: Iterable[ManipulationFlag],
    ) -> None:
        for flag in flags:
            self._conn.execute(
                "INSERT OR REPLACE INTO manipulation_flags VALUES (?, ?, ?)",
                [signal_id, flag.value, detected_at],
            )

    # --- reads ----------------------------------------------------------

    def latest_snapshot(self, market_id: str) -> MarketSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM snapshots WHERE market_id = ? ORDER BY timestamp DESC LIMIT 1",
            [market_id],
        ).fetchone()
        if row is None:
            return None
        return _row_to_snapshot(row)

    def snapshots_in_window(
        self,
        market_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[MarketSnapshot]:
        rows = self._conn.execute(
            """
            SELECT * FROM snapshots
            WHERE market_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
            """,
            [market_id, window_start, window_end],
        ).fetchall()
        return [_row_to_snapshot(row) for row in rows]

    def signals_in_window(
        self,
        market_ids: Sequence[str],
        window_start: datetime,
        window_end: datetime,
    ) -> list[MarketSignal]:
        if not market_ids:
            return []
        # Placeholders interpolated below are "?" characters only; every
        # value is passed as a parameter, not interpolated.
        placeholders = ", ".join(["?"] * len(market_ids))
        query = (
            f"SELECT * FROM signals WHERE market_id IN ({placeholders}) "
            "AND detected_at BETWEEN ? AND ? ORDER BY detected_at ASC"
        )
        rows = self._conn.execute(
            query,
            [*market_ids, window_start, window_end],
        ).fetchall()
        signals = [_row_to_signal(row) for row in rows]
        if not signals:
            return signals
        # Rehydrate manipulation flags from the side table so downstream
        # backtests see the same flag set a consumer would have received
        # at publish time.
        signal_ids = [s.signal_id for s in signals]
        flag_placeholders = ", ".join(["?"] * len(signal_ids))
        flag_query = (
            f"SELECT signal_id, flag FROM manipulation_flags "
            f"WHERE signal_id IN ({flag_placeholders})"
        )
        flag_rows = self._conn.execute(flag_query, list(signal_ids)).fetchall()
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

    def close(self) -> None:
        self._conn.close()


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
            "raw_features": json.loads(raw_features)
            if isinstance(raw_features, str)
            else raw_features,
            "schema_version": schema_version,
        }
    )
