"""`dossier sync` (spec 002)."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import typer

from dossier.application.sync import CHANGES_NAME, SourceReport, changes_artifact, sync_source
from dossier.cli import bootstrap
from dossier.config.credentials import credential_for
from dossier.config.environment import environment
from dossier.config.load import ConfigError, load_pipeline, load_sources
from dossier.domain.tracking import count_metrics, label_for, run_name, sync_description
from dossier.domain.tracking import tags as tracking_tags
from dossier.infrastructure.connectors.registry import (
    UnknownSourceType,
    build_connector,
    declared_keys,
)
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.registry import available_providers
from dossier.infrastructure.store import SnapshotStore


def sync(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    full: bool = typer.Option(
        False,
        "--full",
        help="Ask every source for a full listing, so what it dropped is tombstoned.",
    ),
    label: str = typer.Option(
        "", "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
    ),
) -> None:
    """Fetch only what changed for the sources a pipeline declares (R2.12).

    `--full` lists every source without a window (R2.22). A source that narrows
    its listings is subtracted from only against a full one, which otherwise
    happens on the first sync and on a `fields` change alone.
    """
    workspace = Path.cwd()
    started_at = datetime.now(UTC)

    try:
        config = load_pipeline(
            bootstrap.pipeline_path(workspace, pipeline), providers=available_providers()
        )
        declared = {
            source.id: source
            for source in load_sources(workspace / "sources.yaml", connectors=declared_keys())
        }
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    missing = [name for name in config.synced_sources if name not in declared]
    if missing:
        typer.echo(
            f"pipeline {pipeline!r} names sources not in sources.yaml: {missing}", err=True
        )
        raise typer.Exit(code=2)

    tracker, experiment = bootstrap.tracking_for(workspace, pipeline, kind="sync")

    store = SnapshotStore(workspace)
    reports: list[SourceReport] = []
    # What this sync printed about its work, kept so the record can hold
    # the same lines rather than a second rendering of the same counts
    # (R11.17). The per-item lines are not here: `changes.json` already
    # carries them in full, and a description is a summary (R11.6).
    printed: list[str] = []

    with Ledger(workspace) as ledger:
        for name in config.synced_sources:
            source = declared[name]
            try:
                # Read here, by the one package that reads the environment, and
                # handed to the connector. Infrastructure may not go looking for
                # it itself, and the layer contract enforces that (R1.8). Read
                # through the same environment an endpoint is -- the shell, with
                # `.env` beneath it -- so one file holds every per-machine value
                # (R1.8 row 5, R9.11).
                connector = build_connector(
                    source,
                    workspace=workspace,
                    credential=credential_for(source, environ=environment(workspace)),
                )
            except (UnknownSourceType, ValueError, ConfigError) as error:
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error

            report = sync_source(
                config=source,
                connector=connector,
                store=store,
                ledger=ledger,
                now=started_at,
                full=full,
            )
            reports.append(report)
            printed.append(_source_line(report))
            typer.echo(printed[-1])
            if report.listing_failed is not None:
                # A summary of the source, not an item's line, so the record
                # keeps it too; and the sources after it still sync (R2.27).
                printed.append(f"{report.source_id}: listing failed: {report.listing_failed}")
                typer.echo(printed[-1], err=True)
            for line in _named_lines(report):
                typer.echo(line)
            for key, error in report.failures:
                # With the error the source gave: "failed" alone sends someone to
                # guess whether it was a timeout, a permission or a bad item
                # (R2.13 row 4).
                typer.echo(f"  {report.source_id}: {key} failed: {error}", err=True)

    written = sum(report.snapshots_written for report in reports)
    tombstoned = sum(report.tombstoned for report in reports)
    printed.append(f"ledger updated · {written} new snapshots · {tombstoned} tombstoned")
    typer.echo(printed[-1])

    if tracker is not None:
        # One MLflow run of the per-source counts the lines above printed, under
        # the same names, and no traces (R11.4).
        tracker.start_run(
            experiment=experiment or "",
            name=run_name(
                kind="sync",
                values={
                    "pipeline": pipeline,
                    "started": f"{started_at:%Y%m%dT%H%M%SZ}",
                    "label": label_for(label, environment(workspace)),
                },
                environ=environment(workspace),
            ),
            tags=tracking_tags(
                kind="sync",
                pipeline=pipeline,
                label=label_for(label, environment(workspace)),
                environ=environment(workspace),
            ),
        )
        # Which dossier fetched this, on the record of the fetching
        # (R11.19). The ledger holds no such field, so a sync whose counts
        # look wrong could not be tied to a version at all.
        tracker.log_params({"dossier_version": version("dossier")})
        metrics: dict[str, float] = {}
        for report in reports:
            metrics.update(
                count_metrics(
                    kind="sync",
                    source=report.source_id,
                    counts={
                        "known": report.known,
                        "changed": report.changed,
                        "new": report.new,
                        "returned": len(report.returned),
                        "fetched": report.fetched,
                        "failed": len(report.failed),
                    },
                )
            )
        tracker.log_metrics(metrics)
        # What the lines under each source named, handed over as the report's
        # own list rather than read back from the ledger (R11.6).
        tracker.log_artifact(CHANGES_NAME, changes_artifact(reports))
        # Written as the run closes, because none of these counts exist
        # until the sources have been asked (R11.17).
        tracker.describe(sync_description(pipeline=pipeline, lines=printed))
        failed_items = any(report.failed or report.listing_failed for report in reports)
        tracker.end_run(status="FAILED" if failed_items else "FINISHED")

    failed = [key for report in reports for key in report.failed]
    unlisted = [report.source_id for report in reports if report.listing_failed is not None]
    if failed:
        typer.echo(f"{len(failed)} item(s) failed: {', '.join(sorted(failed))}", err=True)
    if unlisted:
        typer.echo(
            f"{len(unlisted)} source(s) could not be listed: {', '.join(unlisted)}", err=True
        )
    if failed or unlisted:
        raise typer.Exit(code=1)


def _source_line(report: SourceReport) -> str:
    """One line per source, in the shape the design deck publishes (R2.13).

    A source where nothing changed is still printed. A silent source is
    indistinguishable from one that was skipped, and the whole promise of
    incremental sync is that you can see what it did.
    """
    # Printed only when something came back, so a sync where nothing did reads
    # as it always has (R2.25).
    returned = f" · {len(report.returned)} returned" if report.returned else ""
    return (
        f"{report.source_id}  {report.known} known · {report.changed} changed · "
        f"{report.new} new{returned} -> {report.fetched} fetched"
    )


def _named_lines(report: SourceReport) -> list[str]:
    """What moved and what left, one item per line under its source (R2.18, R2.20).

    `1 changed` over four thousand items is not something a person can check,
    and `1 tombstoned` says something left and not what. Both addresses of a
    changed item are printed in full: an 8-character prefix reads well and
    opens nothing, and the point of the line is to be able to diff the two
    files it names.
    """
    return [
        *(f"      {item.key}  {item.held} -> {item.now}" for item in report.repointed),
        *(
            f"      {item.key}  returned"
            + (f"  {item.moved.held} -> {item.moved.now}" if item.moved else "")
            for item in report.returned
        ),
        *(f"      {key}  tombstoned" for key in report.departed),
    ]
