"""Cross-package compatibility gate for `augur-labels`.

Runs at package import time and fails loud when the resolved
`augur-signals` version or its schema contract sits outside the
range this `augur-labels` build was compiled against.

See `docs/contracts/cross-package-compatibility.md` for the policy.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Final

# Compatibility window on augur-signals. Change these in lock step
# with the `"augur-signals ~=X.Y.0"` specifier in pyproject.toml and
# with the MODELS_SCHEMA_VERSION expected below.
_SIGNALS_MIN: Final[str] = "0.1.0"
_SIGNALS_LT: Final[str] = "0.2.0"

# Schema-contract major version. Bumping the augur-signals models' major
# schema_version bumps this; augur-labels must be re-released with the
# matching expected value.
_EXPECTED_MODELS_SCHEMA_MAJOR: Final[str] = "1"


class IncompatibleAugurSignalsError(ImportError):
    """Raised when the resolved `augur-signals` violates the compat range."""


def _parse_version(v: str) -> tuple[int, int, int]:
    # Strip PEP 440 suffixes (post/rc/dev); accept "X.Y.Z" prefix.
    core = v.split("+", maxsplit=1)[0].split("-", maxsplit=1)[0]
    parts = core.split(".")
    if len(parts) < 3:
        parts = [*parts, *(["0"] * (3 - len(parts)))]
    try:
        return (
            int(parts[0]),
            int(parts[1]),
            int(
                parts[2].split("rc")[0].split("a")[0].split("b")[0].split("dev")[0].split("post")[0]
                or "0"
            ),
        )
    except ValueError as exc:
        raise IncompatibleAugurSignalsError(f"Unparseable augur-signals version: {v!r}") from exc


def _require_range(installed: str) -> None:
    got = _parse_version(installed)
    lo = _parse_version(_SIGNALS_MIN)
    hi = _parse_version(_SIGNALS_LT)
    if not (lo <= got < hi):
        raise IncompatibleAugurSignalsError(
            f"augur-labels requires augur-signals >={_SIGNALS_MIN},<{_SIGNALS_LT}; "
            f"found {installed}. Align the package versions (same minor) before "
            "running. See docs/contracts/cross-package-compatibility.md."
        )


def _require_schema_major() -> None:
    from augur_signals.models import MODELS_SCHEMA_VERSION

    observed_major = MODELS_SCHEMA_VERSION.split(".", maxsplit=1)[0]
    if observed_major != _EXPECTED_MODELS_SCHEMA_MAJOR:
        raise IncompatibleAugurSignalsError(
            f"augur-labels expects augur-signals MODELS_SCHEMA_VERSION major "
            f"{_EXPECTED_MODELS_SCHEMA_MAJOR}, got "
            f"{MODELS_SCHEMA_VERSION}. This is a cross-package schema "
            "mismatch — upgrade augur-labels or downgrade augur-signals."
        )


def check_compatibility() -> None:
    """Run both gates; raises `IncompatibleAugurSignalsError` on mismatch."""
    try:
        installed = version("augur-signals")
    except PackageNotFoundError as exc:
        raise IncompatibleAugurSignalsError(
            "augur-signals is not installed but is a required dependency "
            "of augur-labels. Install it via `uv sync` or "
            "`pip install augur-signals~=0.1.0`."
        ) from exc
    _require_range(installed)
    _require_schema_major()
