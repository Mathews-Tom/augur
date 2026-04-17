"""Provenance stamping for LLM-generated briefs.

``stamp`` returns a ProvenanceStamp whose ``prompt_hash`` is the
SHA-256 of ``system + "\\n\\n" + user``. Auditors recompute the hash
from the deterministic prompt builder to confirm the model saw
exactly what the record claims; ``formatter_version`` is read from
the installed package metadata so downgrades / upgrades are visible
in the record.
"""

from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version

from pydantic import BaseModel, ConfigDict


class ProvenanceStamp(BaseModel):
    """The immutable provenance triple carried by every brief."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    prompt_hash: str
    formatter_version: str


def _formatter_version() -> str:
    try:
        return version("augur-format")
    except PackageNotFoundError:  # pragma: no cover — only hit in source checkouts
        return "0.0.0+unknown"


def stamp(
    backend_id: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> ProvenanceStamp:
    """Return the ProvenanceStamp for a completion."""
    composite = f"{system_prompt}\n\n{user_prompt}"
    digest = hashlib.sha256(composite.encode("utf-8")).hexdigest()
    return ProvenanceStamp(
        model=f"{model}@{backend_id}",
        prompt_hash=digest,
        formatter_version=_formatter_version(),
    )
