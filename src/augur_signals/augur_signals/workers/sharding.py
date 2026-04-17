"""Deterministic shard-key filter for stateful per-market workers.

Feature workers and detector workers shard by ``market_id`` so the
same market's observations always land on the same replica. The
sharding function is FNV-1a over the UTF-8 bytes of the key modulo
``replica_count``, which is stable across processes and languages.
"""

from __future__ import annotations

_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_U64_MASK = 0xFFFFFFFFFFFFFFFF


def shard_index(key: str, replica_count: int) -> int:
    """Return the 0-based shard index for *key* in a pool of *replica_count*.

    Args:
        key: The shard key (usually ``market_id``).
        replica_count: Total number of replicas in the pool; must be
            positive.

    Returns:
        An integer in ``[0, replica_count)``.

    Raises:
        ValueError: ``replica_count`` is zero or negative.
    """
    if replica_count <= 0:
        raise ValueError("replica_count must be positive")
    digest = _FNV_OFFSET
    for byte in key.encode("utf-8"):
        digest ^= byte
        digest = (digest * _FNV_PRIME) & _U64_MASK
    return digest % replica_count


def owned_by(key: str, replica_id: int, replica_count: int) -> bool:
    """True if *key* is sharded to *replica_id* in a pool of *replica_count*."""
    return shard_index(key, replica_count) == replica_id
