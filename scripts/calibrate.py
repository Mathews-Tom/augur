"""Calibration run entrypoint.

Rebuilds empirical false-positive rates per (detector, market) and
reliability curves per (detector, liquidity_tier) against the current
labeled corpus per docs/methodology/calibration-methodology.md. Output
is written to DuckDB via the calibration layer's storage adapter.

Stub until the signal-extraction core lands.
"""

from __future__ import annotations

import sys


def main() -> int:
    raise NotImplementedError("calibration runner not yet implemented")


if __name__ == "__main__":
    sys.exit(main())
