"""AST-based guard against `datetime.now()` inside detector modules.

The development-plan invariant (§7.2) states that detectors must take
`now` as a parameter; any call to `datetime.now()` from within a
detector module breaks backtest replay determinism. This script walks
the detector package and fails non-zero on any direct call.

Invocation (CI and local pre-commit):

    uv run python scripts/lint_detector_now.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

DETECTOR_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "augur_signals" / "augur_signals" / "detectors"
)


def _calls_datetime_now(tree: ast.Module) -> list[int]:
    """Return the 1-based line numbers of datetime.now() calls in *tree*."""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "now":
            value = func.value
            if isinstance(value, ast.Name) and value.id == "datetime":
                hits.append(node.lineno)
            elif isinstance(value, ast.Attribute) and value.attr == "datetime":
                hits.append(node.lineno)
    return hits


def main() -> int:
    offenders: dict[str, list[int]] = {}
    for path in sorted(DETECTOR_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = _calls_datetime_now(tree)
        if hits:
            offenders[str(path.relative_to(DETECTOR_DIR.parents[3]))] = hits
    if offenders:
        print(
            "datetime.now() usage forbidden in detectors — pass now as a parameter:",
            file=sys.stderr,
        )
        for file, lines in offenders.items():
            for lineno in lines:
                print(f"  {file}:{lineno}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
