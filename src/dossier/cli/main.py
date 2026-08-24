"""The `dossier` command line (specs 002, 003).

The only layer that exits the interpreter, and the only place that knows which
concrete connector, store and ledger are in play -- everything below takes them
as arguments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from dossier.application.sync import SourceReport, sync_source
from dossier.config.load import ConfigError, load_pipeline, load_sources
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
