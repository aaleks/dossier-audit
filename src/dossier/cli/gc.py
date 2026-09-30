"""`dossier gc`: reclaim space without making a kept run irreproducible (spec 016)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dossier.application.gc import apply_plan, gc_plan, plan_size
from dossier.domain.gc import (
    COLLECTED_CACHES,
    KEEP_LAST,
    NOTHING,
    PREVIEWED,
    run_line,
    summary_line,
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
        ),
    ] = KEEP_LAST,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Delete what the preview lists (R16.5)."),
    ] = False,
) -> None:
    """Delete old runs, tries, replays and the cache entries no kept run reads.

    Without `--apply`, print what would go and delete nothing: the first command
    that deletes cannot do so by accident (R16.5).
    """
    workspace = Path.cwd()
    caches = {name: ArtifactCache(workspace, namespace=name) for name in COLLECTED_CACHES}
    plan = gc_plan(
        workspace,
        store=SnapshotStore(workspace),
        caches=caches,
        held=_held_snapshots(workspace),
        keep_last=keep_last,
    )
    if not (plan.runs or plan.tries or plan.replays or plan.entries):
        typer.echo(NOTHING)
        return

    size = plan_size(workspace, plan, caches=caches)
    if apply:
        apply_plan(workspace, plan, caches=caches)
    typer.echo(
        summary_line(
            applied=apply,
            runs=len(plan.runs),
            tries=len(plan.tries),
            replays=len(plan.replays),
            entries=len(plan.entries),
            size=size,
        )
    )
    for run in plan.runs:
        typer.echo(run_line(run, keep_last=keep_last))
    if not apply:
        typer.echo(PREVIEWED)


def _held_snapshots(workspace: Path) -> set[str]:
    """The snapshots the ledger holds now, whose conversions the next run reads (R16.3)."""
    with Ledger(workspace) as ledger:
        return {
            row.content_hash
            for source in ledger.sources()
            for row in ledger.rows(source)
            if row.state == State.ACTIVE
        }
