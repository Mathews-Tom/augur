"""Print a list of runnable worker entrypoints.

``python -m augur_signals.workers`` prints the catalogue of supported
worker kinds and their CMD strings. Each kind has its own ``__main__``
under ``augur_signals.workers.<kind>`` and is invoked as
``python -m augur_signals.workers.<kind>`` in the Kubernetes manifests.
"""

from __future__ import annotations

_CATALOGUE: tuple[tuple[str, str], ...] = (
    ("poller", "python -m augur_signals.workers.poller --platform <polymarket|kalshi>"),
    ("feature", "python -m augur_signals.workers.feature --shard <index>/<count>"),
    ("detector", "python -m augur_signals.workers.detector --shard <index>/<count>"),
    ("manipulation", "python -m augur_signals.workers.manipulation"),
    ("calibration", "python -m augur_signals.workers.calibration"),
    ("dedup", "python -m augur_signals.workers.dedup"),
    ("context_format", "python -m augur_signals.workers.context_format"),
)


def main() -> int:
    print("Runnable augur-signals worker entrypoints:")
    print()
    for kind, invocation in _CATALOGUE:
        print(f"  {kind:<16} {invocation}")
    print()
    print("LLM formatter entrypoint:")
    print("  llm              python -m augur_format.workers.llm")
    print()
    print(
        "Each entrypoint reads config/{bus,storage,observability}.toml "
        "from $AUGUR_CONFIG_DIR and connects to the bus backend "
        "declared in bus.toml. See docs/operations/manual-testing.md "
        "for the local smoke-test stack."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entrypoint wrapper
    import sys

    sys.exit(main())
