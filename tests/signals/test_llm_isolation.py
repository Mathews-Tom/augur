"""Defense-in-depth: assert LLM packages are not importable by default.

The grep-based LLM-import guard catches source-level imports in
``src/augur_signals/``. This test catches the runtime case where a
dependency change or a stray ``uv sync --extra`` pulls an LLM SDK into
the default environment, which would make an accidental ``import
anthropic`` in extraction code silently succeed.

The tested invariant: in the default workspace sync (no optional
extras), none of the LLM SDK packages used anywhere in the project
tree should be importable by the ``augur_signals`` interpreter.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest

FORBIDDEN_IN_DEFAULT_ENV = (
    "anthropic",
    "openai",
    "ollama",
    "llama_cpp",
    "llama_index",
    "langchain",
    "transformers",
    "huggingface_hub",
)


@pytest.mark.unit
@pytest.mark.parametrize("package", FORBIDDEN_IN_DEFAULT_ENV)
def test_llm_sdk_not_installed_in_default_env(package: str) -> None:
    spec = importlib.util.find_spec(package)
    assert spec is None, (
        f"{package!r} is importable in the default environment; "
        f"an LLM SDK leaked into the default dependency set. "
        f"LLM backends are opt-in extras on augur-format only."
    )
