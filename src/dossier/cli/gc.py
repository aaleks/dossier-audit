"""`dossier gc`: reclaim space without making a kept run irreproducible (spec 016)."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from dossier.application.gc import apply_plan, gc_plan, pin_runs, plan_size, record_gc
from dossier.cli import bootstrap
from dossier.config.environment import environment
from dossier.domain.gc import (
    COLLECTED_CACHES,
    KEEP_LAST,
    NOTHING,
    PREVIEWED,
    run_line,
    summary_line,
    unreplayable_line,
    untraced_line,
)
from dossier.domain.sync import State
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore


def gc(
    keep_last: Annotated[
        int,
        typer.Option(
            "--keep-last",
            help="How many runs of each pipeline to keep (R16.2).",
            metavar="N",
            # Every other command reads a pipeline's latest run, and 0 would
            # delete it with one typo (R16.9).
            min=1,
        ),
    ] = KEEP_LAST,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Delete what the preview lists (R16.5)."),
    ] = False,
    keep: Annotated[
        list[str] | None,
        typer.Option(
            "--keep",
            help="Pin a run, so no gc deletes it: writes runs/<RUN>/keep (R16.6).",
            metavar="RUN",
        ),
    ] = None,
) -> None:
    """Delete old runs, tries, replays and the cache entries no kept run reads.

    Without `--apply`, print what would go and delete nothing: the first command
    that deletes cannot do so by accident (R16.5).
    """
    workspace = Path.cwd()
    started = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    # Before any work, as every command's: a template `gc` cannot fill, or a
    # server nobody can reach, is refused now rather than after files are gone
    # (R10.5, R11.28). `gc` belongs to no pipeline.
    tracker, experiment = bootstrap.tracking_for(workspace, None, kind="gc")
    # Before anything is planned: a pin deletes nothing, so it is written with
    # or without --apply, and the plan then sees the run as kept (R16.6).
    try:
        pin_runs(workspace, keep or [])
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    caches = {name: ArtifactCache(workspace, namespace=name) for name in COLLECTED_CACHES}
    plan = gc_plan(
        workspace,
        store=SnapshotStore(workspace),
        caches=caches,
        held=_held_snapshots(workspace),
        keep_last=keep_last,
    )
    # Before what is collected, and on stderr: a run that cannot be reproduced
    # is a finding about the workspace, whatever gc does next (R16.7).
    for run_id, reason in plan.unreplayable:
        typer.echo(unreplayable_line(run_id, reason), err=True)
        if run_id in plan.untraced:
            typer.echo(untraced_line(run_id), err=True)
    if not (plan.runs or plan.tries or plan.replays or plan.entries):
        typer.echo(NOTHING)
        return

    size = plan_size(workspace, plan, caches=caches)
    if apply:
        apply_plan(workspace, plan, caches=caches)
    printed = [
        summary_line(
            applied=apply,
            runs=len(plan.runs),
            tries=len(plan.tries),
            replays=len(plan.replays),
            entries=len(plan.entries),
            size=size,
        ),
        *(run_line(run, keep_last=keep_last) for run in plan.runs),
    ]
    for line in printed:
        typer.echo(line)
    if not apply:
        # A preview deleted nothing, so there is nothing to record, as `--plan`
        # records nothing (R11.28 row 4).
        typer.echo(PREVIEWED)
        return
    if tracker is not None:
        record_gc(
            tracker,
            experiment=experiment or "",
            plan=plan,
            size=size,
            keep_last=keep_last,
            lines=printed,
            started=started,
            environ=environment(workspace),
            dossier_version=version("dossier"),
        )
        # Said where it was made, as `eval` and `calibrate` say theirs: without
        # it, only MLflow knows that `gc` recorded anything (R11.28 row 6).
        typer.echo(f"recorded to MLflow: {experiment}")


def _held_snapshots(workspace: Path) -> set[str]:
    """The snapshots the ledger holds now, whose conversions the next run reads (R16.3)."""
    with Ledger(workspace) as ledger:
        return {
            row.content_hash
            for source in ledger.sources()
            for row in ledger.rows(source)
            if row.state == State.ACTIVE
        }
