"""Canonical JSON formatter for SignalContext.

Serializes a SignalContext with stable key ordering, float rounding,
and ISO-8601 UTC timestamps with a ``Z`` suffix. The determinism
contract: same SignalContext in, byte-identical JSON out across any
number of invocations. Consumers can hash the bytes and rely on
stable equality.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from augur_signals.models import SignalContext

CANONICAL_KEY_ORDER: tuple[str, ...] = (
    "signal",
    "market_question",
    "resolution_criteria",
    "resolution_source",
    "closes_at",
    "related_markets",
    "investigation_prompts",
    "interpretation_mode",
    "schema_version",
)

SIGNAL_KEY_ORDER: tuple[str, ...] = (
    "signal_id",
    "market_id",
    "platform",
    "signal_type",
    "magnitude",
    "direction",
    "confidence",
    "fdr_adjusted",
    "detected_at",
    "window_seconds",
    "liquidity_tier",
    "manipulation_flags",
    "related_market_ids",
    "raw_features",
    "schema_version",
)

RELATED_KEY_ORDER: tuple[str, ...] = (
    "market_id",
    "question",
    "current_price",
    "delta_24h",
    "volume_24h",
    "relationship_type",
    "relationship_strength",
)


def to_canonical_json(context: SignalContext, *, float_decimals: int = 6) -> bytes:
    """Return the canonical JSON bytes for *context*.

    Args:
        context: The SignalContext to serialize.
        float_decimals: Decimal places each float field is rounded to
            before serialization. Must be applied consistently across
            producers and consumers so equality comparison survives
            the round-trip.

    Returns:
        UTF-8 encoded JSON bytes with no whitespace between separators
        and stable key ordering.
    """
    dumped = context.model_dump(mode="json")
    payload: dict[str, Any] = _ordered_dict(dumped, CANONICAL_KEY_ORDER, float_decimals)
    payload["signal"] = _ordered_dict(dumped["signal"], SIGNAL_KEY_ORDER, float_decimals)
    payload["related_markets"] = [
        _ordered_dict(rm, RELATED_KEY_ORDER, float_decimals)
        for rm in dumped.get("related_markets", [])
    ]
    return json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def _ordered_dict(
    source: Mapping[str, Any],
    key_order: tuple[str, ...],
    float_decimals: int,
) -> dict[str, Any]:
    return {key: _round_floats(source[key], float_decimals) for key in key_order if key in source}


def _round_floats(value: Any, float_decimals: int) -> Any:
    if isinstance(value, float):
        return round(value, float_decimals)
    if isinstance(value, list):
        return [_round_floats(v, float_decimals) for v in value]
    if isinstance(value, dict):
        # Sort nested dict keys so producers with variable insertion
        # order (e.g. raw_features populated conditionally by dedup
        # and cluster-merge paths) still emit byte-identical JSON for
        # the same logical payload.
        return {k: _round_floats(value[k], float_decimals) for k in sorted(value)}
    return value


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        iso = obj.isoformat()
        # Pydantic emits "+00:00"; canonicalize to "Z".
        return iso.replace("+00:00", "Z")
    raise TypeError(f"cannot serialize {type(obj).__name__}")
