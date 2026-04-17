"""Cross-package compatibility gate tests.

Both dependent packages (augur-labels, augur-format) run a
`check_compatibility()` at import time. These tests exercise the gate
directly against manufactured version strings so the installed
workspace is not required to simulate a mismatch.
"""

from __future__ import annotations

import pytest

import augur_format._compat as fmt_compat
import augur_labels._compat as lbl_compat


@pytest.mark.unit
def test_parse_version_handles_prerelease_suffixes() -> None:
    assert lbl_compat._parse_version("0.1.0") == (0, 1, 0)
    assert lbl_compat._parse_version("0.1.0rc1") == (0, 1, 0)
    assert lbl_compat._parse_version("0.1.0.post1") == (0, 1, 0)
    assert lbl_compat._parse_version("0.1.0+local") == (0, 1, 0)


@pytest.mark.unit
def test_parse_version_rejects_garbage() -> None:
    with pytest.raises(lbl_compat.IncompatibleAugurSignalsError):
        lbl_compat._parse_version("not-a-version")


@pytest.mark.unit
@pytest.mark.parametrize("good", ["0.1.0", "0.1.3", "0.1.99", "0.1.0rc1"])
def test_require_range_accepts_in_window(good: str) -> None:
    lbl_compat._require_range(good)
    fmt_compat._require_range(good)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["0.0.9", "0.2.0", "0.2.1", "1.0.0"])
def test_require_range_rejects_out_of_window(bad: str) -> None:
    with pytest.raises(lbl_compat.IncompatibleAugurSignalsError, match="augur-signals"):
        lbl_compat._require_range(bad)
    with pytest.raises(fmt_compat.IncompatibleAugurSignalsError, match="augur-signals"):
        fmt_compat._require_range(bad)


@pytest.mark.unit
def test_require_schema_major_accepts_current() -> None:
    lbl_compat._require_schema_major()
    fmt_compat._require_schema_major()


@pytest.mark.unit
def test_require_schema_major_rejects_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import augur_signals.models as signals_models

    monkeypatch.setattr(signals_models, "MODELS_SCHEMA_VERSION", "2.0.0")
    with pytest.raises(lbl_compat.IncompatibleAugurSignalsError, match="schema"):
        lbl_compat._require_schema_major()
    with pytest.raises(fmt_compat.IncompatibleAugurSignalsError, match="schema"):
        fmt_compat._require_schema_major()


@pytest.mark.unit
def test_check_compatibility_succeeds_on_current_workspace() -> None:
    # Workspace editable install means augur-signals resolves to 0.1.0
    # and MODELS_SCHEMA_VERSION is "1.0.0"; both gates pass.
    lbl_compat.check_compatibility()
    fmt_compat.check_compatibility()


@pytest.mark.unit
def test_exported_version_is_aligned() -> None:
    import augur_format
    import augur_labels

    assert augur_labels.__version__ == "0.1.0"
    assert augur_format.__version__ == "0.1.0"
