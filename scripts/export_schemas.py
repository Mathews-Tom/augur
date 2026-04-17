"""Export Pydantic model JSON schemas to the schemas/ directory.

Usage:
    python scripts/export_schemas.py            # write schemas to disk
    python scripts/export_schemas.py --check    # verify committed schemas match models

The command is intentionally narrow: it serializes every registered
Pydantic model to a deterministic JSON document at
``schemas/<ModelName>-<version>.json``. ``--check`` compares the on-disk
snapshot byte-for-byte against the model's current schema and exits
non-zero on drift; this is the CI gate that enforces schema-contract
discipline per docs/contracts/schema-and-versioning.md.

The model registry below is empty while the Pydantic models live in
future commits. Each model is registered by importing it here and
appending ``(ModelClass, "1.0.0")`` to ``MODELS``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

# Registered (model_class, schema_version) pairs. Extended as Pydantic
# models land. Entries here drive both the write path and the
# --check gate.
MODELS: list[tuple[type[BaseModel], str]] = []


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


def check_schema(model_cls: type[BaseModel], version: str) -> bool:
    """Return True if the on-disk schema matches the current model."""
    path = schema_path(model_cls.__name__, version)
    if not path.exists():
        return False
    return path.read_text(encoding="utf-8") == serialize(model_cls)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed schemas are in sync with current models",
    )
    args = parser.parse_args()

    if args.check:
        drift: list[str] = []
        for model_cls, version in MODELS:
            if not check_schema(model_cls, version):
                drift.append(f"{model_cls.__name__}-{version}")
        if drift:
            print("Schema drift detected:", ", ".join(drift), file=sys.stderr)
            return 1
        print("All schemas in sync.")
        return 0

    for model_cls, version in MODELS:
        export_schema(model_cls, version)
        print(f"Exported {model_cls.__name__}-{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
