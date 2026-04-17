"""augur-label CLI entrypoint.

Commands mirror phase-2 §4: discover, candidates, inspect, decide,
promote, correct, agreement, coverage. The CLI wires an in-memory
CandidateQueue to the WorkflowEnforcer and the AppendOnlyParquetWriter
so annotators can record decisions and promote candidates into the
labeled corpus.

The CLI is deliberately stateless across invocations in the sense that
the corpus on disk is authoritative; in-memory queue state is
rebuilt on each invocation from the queue-state file the caller
passes via --queue-file. For production deployments a persistent
queue backend (sqlite or postgres) replaces the JSON file.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import click

from augur_labels._config import LabelingConfig
from augur_labels.annotator.candidate_queue import CandidateQueue
from augur_labels.annotator.workflow import WorkflowEnforcer
from augur_labels.models import (
    EventCandidate,
    LabelDecision,
    NewsworthyEvent,
)
from augur_labels.storage.parquet_writer import AppendOnlyParquetWriter
from augur_labels.storage.reader import LabelReader


def _queue_path(queue_file: str | None) -> Path:
    return Path(queue_file or "labels/queue.json")


def _load_queue(path: Path) -> CandidateQueue:
    queue = CandidateQueue()
    if not path.exists():
        return queue
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = [EventCandidate.model_validate(item) for item in data.get("candidates", [])]
    queue.enqueue(candidates)
    for raw in data.get("decisions", []):
        queue.record(LabelDecision.model_validate(raw))
    return queue


def _save_queue(queue: CandidateQueue, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "candidates": [c.model_dump(mode="json") for c in queue.all_candidates()],
        "decisions": [d.model_dump(mode="json") for d in queue.all_decisions()],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_config(config_path: str | None) -> LabelingConfig:
    # The CLI accepts --config for tests; production reads config/labeling.toml
    # via the standard augur_signals._config.load_config path.
    if config_path is None:
        return LabelingConfig()
    import tomllib

    with Path(config_path).open("rb") as handle:
        return LabelingConfig.model_validate(tomllib.load(handle))


@click.group()
@click.option("--queue-file", type=click.Path(), default=None, help="Queue state file path")
@click.option("--config", type=click.Path(), default=None, help="Labeling config file path")
@click.pass_context
def cli(ctx: click.Context, queue_file: str | None, config: str | None) -> None:
    """augur-label — annotator CLI for the labeled newsworthy-event corpus."""
    ctx.ensure_object(dict)
    ctx.obj["queue_file"] = _queue_path(queue_file)
    ctx.obj["queue"] = _load_queue(ctx.obj["queue_file"])
    ctx.obj["config"] = _load_config(config)


@cli.command("candidates")
@click.pass_context
def cmd_candidates(ctx: click.Context) -> None:
    """List pending candidates."""
    queue: CandidateQueue = ctx.obj["queue"]
    pending = queue.pending()
    if not pending:
        click.echo("no pending candidates")
        return
    for candidate in pending:
        click.echo(
            f"{candidate.candidate_id}\tpubs={len(candidate.publications)}"
            f"\tmarkets={','.join(candidate.suggested_market_ids)}"
        )


@cli.command("inspect")
@click.argument("candidate_id")
@click.pass_context
def cmd_inspect(ctx: click.Context, candidate_id: str) -> None:
    """Show all publications and suggested markets for a candidate."""
    queue: CandidateQueue = ctx.obj["queue"]
    if candidate_id not in queue:
        click.echo(f"unknown candidate_id={candidate_id!r}", err=True)
        ctx.exit(1)
    candidate = queue.get(candidate_id)
    click.echo(f"candidate_id: {candidate.candidate_id}")
    click.echo(f"discovered_at: {candidate.discovered_at.isoformat()}")
    click.echo(f"suggested_market_ids: {','.join(candidate.suggested_market_ids)}")
    for pub in candidate.publications:
        click.echo(f"  [{pub.source_id}] {pub.timestamp.isoformat()} — {pub.headline}")


@cli.command("decide")
@click.argument("candidate_id")
@click.option("--annotator", "annotator_id", required=True)
@click.option("--qualifies/--reject", default=True)
@click.option("--timestamp", "ts_iso", default=None)
@click.option("--market-ids", default="")
@click.option("--category", default=None)
@click.option("--notes", default=None)
@click.pass_context
def cmd_decide(
    ctx: click.Context,
    candidate_id: str,
    annotator_id: str,
    qualifies: bool,
    ts_iso: str | None,
    market_ids: str,
    category: str | None,
    notes: str | None,
) -> None:
    """Record an annotator's decision on a candidate."""
    queue: CandidateQueue = ctx.obj["queue"]
    ts = datetime.fromisoformat(ts_iso) if ts_iso and qualifies else None
    markets = [m.strip() for m in market_ids.split(",") if m.strip()] if qualifies else []
    decision = LabelDecision(
        decision_id=str(uuid4()),
        candidate_id=candidate_id,
        annotator_id=annotator_id,
        decided_at=datetime.now(tz=UTC),
        qualifies=qualifies,
        timestamp=ts,
        market_ids=markets,
        category=category if qualifies else None,
        notes=notes,
    )
    queue.record(decision)
    _save_queue(queue, ctx.obj["queue_file"])
    click.echo(f"recorded decision {decision.decision_id}")


@cli.command("promote")
@click.argument("candidate_id")
@click.pass_context
def cmd_promote(ctx: click.Context, candidate_id: str) -> None:
    """Promote a qualifying candidate into the labeled corpus."""
    queue: CandidateQueue = ctx.obj["queue"]
    config: LabelingConfig = ctx.obj["config"]
    enforcer = WorkflowEnforcer(config.workflow, queue)
    decision = enforcer.can_promote(candidate_id)
    if not decision.allowed:
        click.echo(f"cannot promote: {decision.reason}", err=True)
        ctx.exit(1)
    for warning in enforcer.promotion_warnings(candidate_id):
        click.echo(f"warning: {warning}", err=True)
    event = _compose_event(queue, candidate_id)
    writer = AppendOnlyParquetWriter(Path(config.storage.labels_root))
    writer.append([event])
    click.echo(f"promoted {candidate_id} to event {event.event_id}")


@cli.command("correct")
@click.argument("event_id")
@click.option("--replacement-id", required=True)
@click.pass_context
def cmd_correct(ctx: click.Context, event_id: str, replacement_id: str) -> None:
    """Mark an existing event as superseded by *replacement_id*."""
    config: LabelingConfig = ctx.obj["config"]
    writer = AppendOnlyParquetWriter(Path(config.storage.labels_root))
    writer.supersede(event_id, replacement_id)
    click.echo(f"superseded {event_id} → {replacement_id}")


@cli.command("coverage")
@click.option("--since", "since_iso", default=None)
@click.pass_context
def cmd_coverage(ctx: click.Context, since_iso: str | None) -> None:
    """Print labeled-event counts per category since *since*."""
    config: LabelingConfig = ctx.obj["config"]
    since = datetime.fromisoformat(since_iso) if since_iso else datetime(2020, 1, 1, tzinfo=UTC)
    reader = LabelReader(Path(config.storage.labels_root))
    counts = reader.coverage_by_category(since=since)
    for category, count in sorted(counts.items()):
        click.echo(f"{category}\t{count}")


def _compose_event(queue: CandidateQueue, candidate_id: str) -> NewsworthyEvent:
    """Build a NewsworthyEvent from the qualifying decisions."""
    candidate = queue.get(candidate_id)
    decisions = [d for d in queue.decisions_for(candidate_id) if d.qualifies]
    timestamps = [d.timestamp for d in decisions if d.timestamp is not None]
    ground_truth = min(timestamps) if timestamps else candidate.discovered_at
    market_sets = [set(d.market_ids) for d in decisions]
    merged_markets = sorted(set.union(*market_sets)) if market_sets else []
    categories = [d.category for d in decisions if d.category]
    category = categories[0] if categories else "markets"
    headline = candidate.publications[0].headline if candidate.publications else ""
    source_urls = [str(pub.url) for pub in candidate.publications]
    source_publishers = [pub.source_id for pub in candidate.publications]
    labeler_ids = sorted({d.annotator_id for d in decisions})
    return NewsworthyEvent(
        event_id=str(uuid4()),
        ground_truth_timestamp=ground_truth,
        market_ids=merged_markets,
        category=category,
        headline=headline,
        source_urls=source_urls,
        source_publishers=source_publishers,
        labeler_ids=labeler_ids,
        label_protocol_version="1.0",
        corrects=None,
        status="labeled",
        created_at=datetime.now(tz=UTC),
    )


if __name__ == "__main__":  # pragma: no cover
    cli()
