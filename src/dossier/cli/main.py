"""The `dossier` command line (specs 002, 003).

The only layer that exits the interpreter, and the only place that knows which
concrete connector, store and ledger are in play -- everything below takes them
as arguments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from dossier.application.plan import (
    StepStatus,
    build_plan,
    latest_manifest,
    pinned_documents,
)
from dossier.application.sync import SourceReport, sync_source
from dossier.config.load import ConfigError, load_pipeline, load_sources
from dossier.domain.hashing import content_hash
from dossier.infrastructure.connectors.registry import UnknownSourceType, build_connector
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

app = typer.Typer(add_completion=False)


@app.callback()
def main() -> None:
    """Collect documents, audit them, and prove the result.

    A callback is declared so that `sync` stays a sub-command. Typer collapses
    a single-command app into a bare invocation, and `dossier <pipeline>` is
    not the interface the specs describe -- `run` and `eval` join it later.
    """


@app.command()
def sync(pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/")) -> None:
    """Fetch only what changed for the sources a pipeline declares (R2.12)."""
    workspace = Path.cwd()
    started_at = datetime.now(UTC)

    try:
        config = load_pipeline(_pipeline_path(workspace, pipeline))
        declared = {source.id: source for source in load_sources(workspace / "sources.yaml")}
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    missing = [name for name in config.synced_sources if name not in declared]
    if missing:
        typer.echo(
            f"pipeline {pipeline!r} names sources not in sources.yaml: {missing}", err=True
        )
        raise typer.Exit(code=2)

    store = SnapshotStore(workspace)
    reports: list[SourceReport] = []

    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            source = declared[name]
            try:
                connector = build_connector(source, workspace=workspace)
            except (UnknownSourceType, ValueError) as error:
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error

            report = sync_source(
                config=source,
                connector=connector,
                store=store,
                ledger=ledger,
                now=started_at,
            )
            reports.append(report)
            typer.echo(_source_line(report))

    written = sum(report.snapshots_written for report in reports)
    tombstoned = sum(report.tombstoned for report in reports)
    typer.echo(f"ledger updated · {written} new snapshots · {tombstoned} tombstoned")

    failed = [key for report in reports for key in report.failed]
    if failed:
        typer.echo(f"{len(failed)} item(s) failed: {', '.join(sorted(failed))}", err=True)
        raise typer.Exit(code=1)


def _source_line(report: SourceReport) -> str:
    """One line per source, in the shape the design deck publishes (R2.13).

    A source where nothing changed is still printed. A silent source is
    indistinguishable from one that was skipped, and the whole promise of
    incremental sync is that you can see what it did.
    """
    return (
        f"{report.source_id}  {report.known} known · {report.changed} changed · "
        f"{report.new} new -> {report.fetched} fetched"
    )


def _pipeline_path(workspace: Path, name: str) -> Path:
    path = workspace / "pipelines" / name / "pipeline.yaml"
    if not path.exists():
        # Naming where it looked matters more than naming what is missing: the
        # usual cause is being in the wrong directory (R2.12 example 3).
        raise ConfigError(f"no pipeline {name!r}: expected {path}")
    return path


def build_model_client(model_id: str):
    """Resolve a pinned model identifier to a client.

    Not implemented yet, and deliberately a named function rather than an inline
    construction: it is the seam the composition root hands to a use case, and
    R4.6 is the claim that `--plan` never reaches it. A test replaces this and
    asserts it was never called.
    """
    raise NotImplementedError(
        f"no model client is wired up yet for {model_id!r}. "
        "`--plan` does not need one; executing a run will."
    )


@app.command()
def run(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    plan: bool = typer.Option(False, "--plan", help="Report what would run. Do nothing."),
) -> None:
    """Execute a pipeline, or report what executing it would do (spec 004)."""
    if not plan:
        # Stated rather than half-built. Executing needs the cache and the
        # provenance record that spec 005 defines, and a `run` that quietly did
        # something less than that would be worse than one that says so.
        typer.echo("only `--plan` is implemented so far; pass --plan", err=True)
        raise typer.Exit(code=2)

    workspace = Path.cwd()

    try:
        path = _pipeline_path(workspace, pipeline)
        config = load_pipeline(path)
        declared = {source.id: source for source in load_sources(workspace / "sources.yaml")}
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    documents: dict[str, str] = {}
    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            if name in declared:
                documents.update(pinned_documents(ledger.rows(name)))

    previous, previous_id = latest_manifest(workspace / "runs", pipeline)

    try:
        report = build_plan(
            pipeline=config,
            pipeline_hash=content_hash(path.read_bytes()),
            documents=documents,
            previous=previous,
            previous_id=previous_id,
        )
    except ValueError as error:
        # Resolution failed, so nothing ran and nothing was written (R4.1).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    for line in _plan_lines(report):
        typer.echo(line)


def _plan_lines(report) -> list[str]:
    """The plan as a person reads it: one step per line, evidence indented.

    A step whose inputs moved prints what they were and what they are now. That
    is the whole point of the command -- an insertion looks local in the YAML and
    silently re-points every relative reference below it (R4.5).
    """
    lines = [
        f"{report.resolved.pipeline}  {len(report.resolved.documents)} document(s) · "
        f"model {report.resolved.model}"
    ]
    if report.compared_against is None:
        lines.append("no previous run to compare against")
    else:
        lines.append(f"compared against {report.compared_against}")

    for step in report.steps:
        marker = " " if step.status is StepStatus.CACHED else "!"
        lines.append(f"{marker} {step.step.id}: {step.status.value}")
        if step.was is not None:
            lines.append(f"      was: [{', '.join(step.was)}]")
            lines.append(f"      now: [{', '.join(step.step.inputs)}]")

    lines.append(
        f"{report.rerunning} of {len(report.steps)} step(s) would run · nothing written"
    )
    return lines
