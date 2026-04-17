"""TOML configuration loader with Pydantic validation.

Loads a single TOML file and validates it against the caller-supplied
Pydantic model. Fails loud on missing files and validation errors — the
caller is expected to surface the exception; this module applies no
defaults and performs no fallback.

Per-config Pydantic models live alongside the consuming subpackage
(for example, augur_signals.detectors._config defines DetectorsConfig).
The engine startup path composes these models into the overall runtime
configuration.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel


def load_config[C: BaseModel](path: Path, model: type[C]) -> C:
    """Load a TOML file from *path* and validate against *model*.

    Args:
        path: Filesystem location of the TOML file. Absolute or
            relative to the current working directory.
        model: Pydantic BaseModel subclass describing the expected
            schema.

    Returns:
        An instance of *model* populated from the TOML contents.

    Raises:
        FileNotFoundError: The file does not exist on disk.
        pydantic.ValidationError: The file's contents do not match
            *model*'s schema.
        tomllib.TOMLDecodeError: The file is not valid TOML.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return model.model_validate(raw)
