"""Export Pydantic model JSON schemas to the schemas/ directory.

Usage:
    python scripts/export_schemas.py            # write schemas to disk
    python scripts/export_schemas.py --check    # verify committed schemas match models

The command is intentionally narrow: it serializes every registered
Pydantic model to a deterministic JSON document at
schemas/<ModelName>-<version>.json. --check compares the on-disk
snapshot byte-for-byte against the model's current schema and exits
non-zero on drift; this is the CI gate that enforces schema-contract
discipline per docs/contracts/schema-and-versioning.md.

The model registry below is empty while the Pydantic models live in
future commits. Each model is registered by importing it here and
appending (ModelClass, "1.0.0") to MODELS.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from augur_format.llm.models import IntelligenceBrief
from augur_signals.models import (
    FeatureVector,
    MarketSignal,
    MarketSnapshot,
    SignalContext,
)

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

# Registered (model_class, schema_version) pairs. Entries drive both
# the write path and the --check gate.
MODELS: list[tuple[type[BaseModel], str]] = [
    (MarketSnapshot, "1.0.0"),
    (FeatureVector, "1.0.0"),
    (MarketSignal, "1.0.0"),
    (SignalContext, "1.0.0"),
    (IntelligenceBrief, "1.0.0"),
]


def schema_path(model_name: str, version: str) -> Path:
    """Canonical on-disk location for a model's exported schema."""
    return SCHEMAS_DIR / f"{model_name}-{version}.json"


def serialize(model_cls: type[BaseModel]) -> str:
    """Serialize a model's JSON schema to a deterministic string."""
    return json.dumps(model_cls.model_json_schema(), indent=2, sort_keys=True) + "\n"


def export_schema(model_cls: type[BaseModel], version: str) -> None:
    """Write the model's schema to disk."""
    out = schema_path(model_cls.__name__, version)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(serialize(model_cls), encoding="utf-8")


def check_schema(model_cls: type[BaseModel], version: str) -> tuple[bool, bool]:
    """Compare on-disk schema to the current model.

    Returns a (exists, matches) pair. exists is False when the
    schema file is missing on disk; matches is True only when the
    file exists and its contents are byte-for-byte identical to the
    serialized model. The split lets the caller distinguish a missing
    file from a content drift and report them separately.
    """
    path = schema_path(model_cls.__name__, version)
    if not path.exists():
        return False, False
    return True, path.read_text(encoding="utf-8") == serialize(model_cls)


def find_orphan_schemas() -> list[str]:
    """Return schema filenames on disk with no corresponding MODELS entry.

    The schemas/ directory is machine-managed; any file that does not
    trace to a registered (model, version) pair indicates a stale or
    hand-edited schema. The --check mode treats orphans as drift so
    they do not accumulate silently.
    """
    expected = {f"{cls.__name__}-{ver}.json" for cls, ver in MODELS}
    if not SCHEMAS_DIR.exists():
        return []
    return sorted(
        p.name
        for p in SCHEMAS_DIR.iterdir()
        if p.is_file() and p.suffix == ".json" and p.name not in expected
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed schemas are in sync with current models",
    )
    args = parser.parse_args()

    if args.check:
        missing: list[str] = []
        drifted: list[str] = []
        for model_cls, version in MODELS:
            exists, matches = check_schema(model_cls, version)
            label = f"{model_cls.__name__}-{version}"
            if not exists:
                missing.append(label)
            elif not matches:
                drifted.append(label)
        orphans = find_orphan_schemas()

        if missing:
            print("Schema files missing:", ", ".join(missing), file=sys.stderr)
        if drifted:
            print("Schema drift detected:", ", ".join(drifted), file=sys.stderr)
        if orphans:
            print("Orphan schemas on disk:", ", ".join(orphans), file=sys.stderr)
        if missing or drifted or orphans:
            return 1
        print("All schemas in sync.")
        return 0

    for model_cls, version in MODELS:
        export_schema(model_cls, version)
        print(f"Exported {model_cls.__name__}-{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
