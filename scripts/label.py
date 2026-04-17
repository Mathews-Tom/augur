"""Annotator CLI entrypoint.

Launches the two-annotator labeling workflow over the newsworthy-event
feed per docs/methodology/labeling-protocol.md and persists labels to
``labels/newsworthy_events.parquet``.

Stub until the labeling workstream lands.
"""

from __future__ import annotations

import sys


def main() -> int:
    raise NotImplementedError("annotator CLI not yet implemented")


if __name__ == "__main__":
    sys.exit(main())
