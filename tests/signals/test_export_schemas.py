"""Tests for the schema export tool.

The CI gate relies on three distinct failure modes being reported:
missing schema files, content drift, and orphans on disk. Each is
exercised here against an isolated MODELS registry and temporary
SCHEMAS_DIR; the real registry (empty at scaffolding time) is not
mutated.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel


def _reload_export_schemas(tmp_path: Path) -> object:
    # Insert scripts/ on sys.path lazily so the module can be imported.
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import export_schemas

    importlib.reload(export_schemas)
    export_schemas.SCHEMAS_DIR = tmp_path  # type: ignore[attr-defined]
    return export_schemas


class _SampleModel(BaseModel):
    name: str
    value: int


@pytest.mark.unit
def test_export_writes_deterministic_schema(tmp_path: Path) -> None:
    mod = _reload_export_schemas(tmp_path)
    mod.MODELS.append((_SampleModel, "1.0.0"))  # type: ignore[attr-defined]
    mod.export_schema(_SampleModel, "1.0.0")  # type: ignore[attr-defined]

    out = tmp_path / "_SampleModel-1.0.0.json"
    assert out.exists()
    first = out.read_text(encoding="utf-8")
    mod.export_schema(_SampleModel, "1.0.0")  # type: ignore[attr-defined]
    assert out.read_text(encoding="utf-8") == first


@pytest.mark.unit
def test_check_reports_missing_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod = _reload_export_schemas(tmp_path)
    mod.MODELS.append((_SampleModel, "1.0.0"))  # type: ignore[attr-defined]

    sys.argv = ["export_schemas.py", "--check"]
    rc = mod.main()  # type: ignore[attr-defined]

    assert rc == 1
    captured = capsys.readouterr()
    assert "missing" in captured.err.lower()
    assert "_SampleModel-1.0.0" in captured.err


@pytest.mark.unit
def test_check_reports_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod = _reload_export_schemas(tmp_path)
    mod.MODELS.append((_SampleModel, "1.0.0"))  # type: ignore[attr-defined]
    (tmp_path / "_SampleModel-1.0.0.json").write_text("{}\n", encoding="utf-8")

    sys.argv = ["export_schemas.py", "--check"]
    rc = mod.main()  # type: ignore[attr-defined]

    assert rc == 1
    captured = capsys.readouterr()
    assert "drift" in captured.err.lower()


@pytest.mark.unit
def test_check_reports_orphans(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod = _reload_export_schemas(tmp_path)
    (tmp_path / "StaleModel-9.9.9.json").write_text("{}\n", encoding="utf-8")

    sys.argv = ["export_schemas.py", "--check"]
    rc = mod.main()  # type: ignore[attr-defined]

    assert rc == 1
    captured = capsys.readouterr()
    assert "orphan" in captured.err.lower()
    assert "StaleModel-9.9.9.json" in captured.err


@pytest.mark.unit
def test_check_succeeds_when_synced(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod = _reload_export_schemas(tmp_path)
    mod.MODELS.append((_SampleModel, "1.0.0"))  # type: ignore[attr-defined]
    mod.export_schema(_SampleModel, "1.0.0")  # type: ignore[attr-defined]

    sys.argv = ["export_schemas.py", "--check"]
    rc = mod.main()  # type: ignore[attr-defined]

    assert rc == 0
    captured = capsys.readouterr()
    assert "in sync" in captured.out.lower()
