"""JSON schema validator for outgoing payloads.

Runs in debug builds and integration tests; production skips schema
validation for throughput per the pattern in phase-3 §8.2. The
validator reads exported JSON schemas from ``schemas/`` so producers
and consumers share the same contract snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SCHEMAS_DIR = Path(__file__).resolve().parents[4] / "schemas"


class SchemaNotFoundError(RuntimeError):
    """Raised when the requested schema is absent from schemas/."""


def load_schema(
    model_name: str,
    version: str,
    root: Path | None = None,
) -> dict[str, object]:
    """Load ``schemas/<ModelName>-<version>.json``.

    Missing schemas raise SchemaNotFoundError rather than returning a
    permissive empty dict; a missing schema indicates the export step
    did not run or the wrong version was requested, both of which
    would mask contract drift at the formatter boundary.
    """
    schemas_dir = root or DEFAULT_SCHEMAS_DIR
    target = schemas_dir / f"{model_name}-{version}.json"
    if not target.exists():
        raise SchemaNotFoundError(f"schema not found: {target}")
    with target.open(encoding="utf-8") as handle:
        data: dict[str, object] = json.load(handle)
    return data
