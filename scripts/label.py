"""Annotator CLI entrypoint.

Launches the augur-label click CLI over the newsworthy-event candidate
queue and the append-only parquet corpus. Available commands are
implemented in augur_labels.annotator.cli; run ``python scripts/label.py
--help`` to discover them.
"""

from __future__ import annotations

import sys

from augur_labels.annotator.cli import cli


def main() -> int:
    cli(standalone_mode=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
