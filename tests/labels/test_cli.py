"""Tests for the augur-label CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from augur_labels.annotator.cli import cli
from augur_labels.models import EventCandidate, SourcePublication


def _publication(pub_id: str, source: str = "reuters") -> SourcePublication:
    return SourcePublication(
        publication_id=pub_id,
        source_id=source,  # type: ignore[arg-type]
        timestamp=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        headline="Fed holds rates",
        url="https://example.com/story",  # type: ignore[arg-type]
    )


def _seed_queue(queue_path: Path) -> None:
    candidate = EventCandidate(
        candidate_id="c1",
        discovered_at=datetime(2026, 3, 15, 12, 5, tzinfo=UTC),
        publications=[_publication("p1"), _publication("p2", "bloomberg")],
        suggested_market_ids=["kalshi_fed"],
    )
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        json.dumps(
            {"candidates": [candidate.model_dump(mode="json")], "decisions": []},
            default=str,
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def tmp_paths(tmp_path: Path) -> tuple[Path, Path]:
    queue_path = tmp_path / "queue.json"
    labels_root = tmp_path / "labels"
    _seed_queue(queue_path)
    return queue_path, labels_root


def _common_args(queue_path: Path, labels_root: Path) -> list[str]:
    return ["--queue-file", str(queue_path)]


@pytest.mark.unit
def test_candidates_lists_seeded_candidate(tmp_paths: tuple[Path, Path]) -> None:
    queue_path, labels_root = tmp_paths
    runner = CliRunner()
    result = runner.invoke(cli, [*_common_args(queue_path, labels_root), "candidates"])
    assert result.exit_code == 0
    assert "c1" in result.output


@pytest.mark.unit
def test_inspect_shows_publications(tmp_paths: tuple[Path, Path]) -> None:
    queue_path, labels_root = tmp_paths
    runner = CliRunner()
    result = runner.invoke(cli, [*_common_args(queue_path, labels_root), "inspect", "c1"])
    assert result.exit_code == 0
    assert "Fed holds rates" in result.output


@pytest.mark.unit
def test_inspect_unknown_candidate_exits_nonzero(tmp_paths: tuple[Path, Path]) -> None:
    queue_path, labels_root = tmp_paths
    runner = CliRunner()
    result = runner.invoke(cli, [*_common_args(queue_path, labels_root), "inspect", "missing"])
    assert result.exit_code != 0


@pytest.mark.unit
def test_decide_persists_decision_to_queue_file(tmp_paths: tuple[Path, Path]) -> None:
    queue_path, labels_root = tmp_paths
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            *_common_args(queue_path, labels_root),
            "decide",
            "c1",
            "--annotator",
            "ann1",
            "--timestamp",
            "2026-03-15T12:00:00+00:00",
            "--market-ids",
            "kalshi_fed",
            "--category",
            "monetary_policy",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(data["decisions"]) == 1
    assert data["decisions"][0]["annotator_id"] == "ann1"


@pytest.mark.unit
def test_promote_refuses_with_single_annotator(tmp_paths: tuple[Path, Path]) -> None:
    queue_path, labels_root = tmp_paths
    runner = CliRunner()
    runner.invoke(
        cli,
        [
            *_common_args(queue_path, labels_root),
            "decide",
            "c1",
            "--annotator",
            "ann1",
            "--timestamp",
            "2026-03-15T12:00:00+00:00",
            "--market-ids",
            "kalshi_fed",
        ],
    )
    result = runner.invoke(
        cli, [*_common_args(queue_path, labels_root), "promote", "c1"]
    )
    assert result.exit_code != 0
    assert "two distinct" in result.output


@pytest.mark.unit
def test_promote_writes_event_on_agreement(tmp_paths: tuple[Path, Path]) -> None:
    queue_path, labels_root = tmp_paths
    runner = CliRunner()
    for annotator, offset in [("ann1", 0), ("ann2", 30)]:
        runner.invoke(
            cli,
            [
                *_common_args(queue_path, labels_root),
                "decide",
                "c1",
                "--annotator",
                annotator,
                "--timestamp",
                f"2026-03-15T12:00:{offset:02d}+00:00",
                "--market-ids",
                "kalshi_fed",
                "--category",
                "monetary_policy",
            ],
        )
    # Create a labeling config pointing at labels_root.
    config_path = labels_root.parent / "labeling.toml"
    config_path.write_text(
        f'[storage]\nlabels_root = "{labels_root}"\nfile_lock_timeout_seconds = 30\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        cli,
        [
            "--queue-file",
            str(queue_path),
            "--config",
            str(config_path),
            "promote",
            "c1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "promoted c1" in result.output
    # Partition file exists.
    partitions = list((labels_root).glob("date=*/events.parquet"))
    assert len(partitions) == 1
