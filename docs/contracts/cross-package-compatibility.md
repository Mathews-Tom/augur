# Cross-Package Compatibility Policy

Augur ships as three independent PyPI packages (`augur-signals`, `augur-labels`, `augur-format`). The packages share Pydantic contracts in `augur_signals.models` and must agree on the schema at install time. This document pins the versioning rules and the runtime gates that enforce them.

## Version alignment rule

All three workspace packages are released **in lock step**. A release cuts `vX.Y.Z` for all three simultaneously; there is no release where `augur-labels` and `augur-format` point at different `augur-signals` versions in their pinned range.

### Dependency specifier

Each dependent package pins `augur-signals` with a compatible-release specifier on the minor version:

```toml
# augur-labels/pyproject.toml, augur-format/pyproject.toml
"augur-signals ~= 0.1.0"   # >=0.1.0, <0.2.0
```

Patch upgrades (`0.1.0 → 0.1.1`) are permitted transparently. A minor bump (`0.1.x → 0.2.0`) **must** re-cut `augur-labels` and `augur-format` with an updated specifier before publishing.

### Major vs minor vs patch

Pre-1.0 semantics (0.x phase):

| Bump | When | Downstream action |
| --- | --- | --- |
| `0.1.Z → 0.1.Z+1` | Internal refactor, additive API, bug fix that preserves schema | None. All three packages co-publish a patch. |
| `0.1.Z → 0.2.0` | Breaking change to any exported contract (`MarketSignal`, `SignalContext`, `FeatureVector`, `EventBus`, etc.), even if field-additive | Downstream pin tightens to `~= 0.2.0`; MODELS_SCHEMA_VERSION major may bump. |
| `0.Y.Z → 1.0.0` | API stability commitment | Full semver applies from here on. |

After 1.0, a major bump in `augur-signals` forces a major bump in both dependents (their import-time gates refuse the major-mismatch).

## Runtime compatibility gate

Both `augur-labels` and `augur-format` run a two-part check at package import time. The gate is in each package's `_compat.py` module and is invoked from `__init__.py` *before any public symbol is re-exported*.

### Gate 1 — installed version range

```python
# Parses importlib.metadata.version("augur-signals") and rejects anything
# outside [_SIGNALS_MIN, _SIGNALS_LT).
_SIGNALS_MIN: Final[str] = "0.1.0"
_SIGNALS_LT: Final[str] = "0.2.0"
```

Catches two failure modes:

1. A user ran `pip install --no-deps` or a private index served a broken set.
2. A transitive dependency upgraded `augur-signals` past the compatible range without bumping this package.

### Gate 2 — schema-contract major version

```python
from augur_signals.models import MODELS_SCHEMA_VERSION
# Rejects when the major digit does not match _EXPECTED_MODELS_SCHEMA_MAJOR.
```

`MODELS_SCHEMA_VERSION` is the canonical constant in `augur_signals.models`. Every Pydantic model in that package pins `schema_version: Literal["X.Y.Z"]` to the same value. A major bump in the constant signals a breaking schema change that requires downstream rebuild; the gate refuses to proceed with a mismatched dependent build.

### Failure mode

Both gates raise `IncompatibleAugurSignals`, a subclass of `ImportError`. The error message names the observed version, the expected range, and points at this document. The package fails to import — no partial import, no soft warning, no graceful degradation.

```
augur-labels requires augur-signals >=0.1.0,<0.2.0; found 0.2.3.
Align the package versions (same minor) before running.
See docs/contracts/cross-package-compatibility.md.
```

## Release procedure

1. Change any exported contract in `augur-signals`.
2. If the change is breaking, bump `MODELS_SCHEMA_VERSION` major.
3. Bump all three package versions in lock step:
   - `pyproject.toml` (root)
   - `src/augur_signals/pyproject.toml`
   - `src/augur_labels/pyproject.toml`
   - `src/augur_format/pyproject.toml`
4. Update the dependent pins:
   - `augur-labels` and `augur-format` change `"augur-signals ~= X.Y.0"`.
   - `augur_labels/_compat.py` and `augur_format/_compat.py` update `_SIGNALS_MIN`, `_SIGNALS_LT`, and `_EXPECTED_MODELS_SCHEMA_MAJOR` in the same commit.
5. Update `CHANGELOG.md` under `## [Unreleased]`.
6. Run gates, tag `vX.Y.Z`, build and publish all three wheels in one `uv publish` invocation.

Release automation enforcing the lock-step bump is a follow-up (tracked against v0.2.0).

## Why not collapse into one package

A single `augur` package with optional-dependency subsets would eliminate cross-package version drift at the cost of:

- Losing the physical LLM-isolation boundary (no import of `anthropic` / `ollama` possible anywhere in `augur_signals`). The CI grep guard would become the only defence.
- A larger install closure for deployments that need only one slice (a signal-extraction worker would still resolve the labeling and formatting submodules' metadata).
- Releases coupling bug fixes across domains (a labeling-only patch forces a re-release of the formatter).

The three-package split accepts cross-version drift risk in exchange for enforceable isolation and independently-installable subsets. The gates in this document bound the risk to same-minor drift only.

## Scope

This policy applies only to the three `augur-*` workspace packages. Optional-dependency extras on each package (`llm-local`, `llm-cloud`, `bus-nats`, etc.) follow each wrapped SDK's own versioning conventions and are not gated here.
