"""Backtest harness entrypoint.

Replays historical snapshots from DuckDB through the live signal
pipeline with ``now`` threaded deterministically, then computes
precision / recall / lead-time distributions per detector and liquidity
tier against the labeled corpus per docs/methodology/labeling-protocol.md.

This entrypoint is a stub until the signal-extraction core lands. The
module is importable so the CLI surface can be wired into the engine
early; invocation raises NotImplementedError to make a premature run
loud.
"""

from __future__ import annotations

import sys


def main() -> int:
    raise NotImplementedError("backtest harness not yet implemented")


if __name__ == "__main__":
    sys.exit(main())
