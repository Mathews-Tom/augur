"""Curated historical episodes used as positive-case test fixtures.

Each episode names an identifier, a description, and the set of flags
the manipulation detector is expected to raise when exercised against
the fixture trades, book events, and snapshots. The full event streams
live alongside the tests under tests/_fixtures/manipulation/; this
module provides the canonical metadata so the tests cross-reference
the taxonomy and the detector agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from augur_signals.models import ManipulationFlag


@dataclass(frozen=True, slots=True)
class Episode:
    """One curated manipulation episode."""

    episode_id: str
    description: str
    expected_flags: frozenset[ManipulationFlag] = field(default_factory=frozenset)


CURATED_EPISODES: tuple[Episode, ...] = (
    Episode(
        episode_id="polymarket_2024_election_whale",
        description="Coordinated large trades during the 2024 cycle",
        expected_flags=frozenset(
            {
                ManipulationFlag.SINGLE_COUNTERPARTY_CONCENTRATION,
                ManipulationFlag.SIZE_VS_DEPTH_OUTLIER,
            }
        ),
    ),
    Episode(
        episode_id="polymarket_2024_mid_curve_squeeze",
        description="Mid-curve squeeze on a thin contract",
        expected_flags=frozenset(
            {
                ManipulationFlag.THIN_BOOK_DURING_MOVE,
                ManipulationFlag.SIZE_VS_DEPTH_OUTLIER,
            }
        ),
    ),
    Episode(
        episode_id="polymarket_2024_settlement_pump",
        description="Pre-resolution pump on a sports contract",
        expected_flags=frozenset(
            {
                ManipulationFlag.PRE_RESOLUTION_WINDOW,
                ManipulationFlag.SIZE_VS_DEPTH_OUTLIER,
            }
        ),
    ),
    Episode(
        episode_id="polymarket_2025_layering",
        description="Layering pattern on an economic-indicator contract",
        expected_flags=frozenset({ManipulationFlag.CANCEL_REPLACE_BURST}),
    ),
    Episode(
        episode_id="polymarket_2025_wash_low_volume",
        description="Wash-trading on a crypto-regulatory contract",
        expected_flags=frozenset(
            {
                ManipulationFlag.SINGLE_COUNTERPARTY_CONCENTRATION,
                ManipulationFlag.THIN_BOOK_DURING_MOVE,
            }
        ),
    ),
)
