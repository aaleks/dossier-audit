"""Working out what a run would do, without doing any of it (spec 004).

`--plan` is the command you run when you do not trust what is about to happen,
so the one thing it must never do is change the answer. Nothing here writes, and
nothing here constructs a model client -- the composition root does not even ask
for one on this path (R4.6).

Reading is permitted and necessary: the pipeline, the ledger, and the most
recent manifest for this pipeline all have to be opened to say anything useful.
The rule forbids calling and writing, not reading.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dossier.application.manifest import MANIFEST_NAME, read_manifest
from dossier.domain.pipeline import PipelineConfig
from dossier.domain.plan import StepPlan, diff
from dossier.domain.resolution import PinnedConverter, ResolvedPlan, resolve
from dossier.domain.store import FAILURES_NAME
from dossier.domain.sync import State


@dataclass(frozen=True)
class Plan:
    """What a run would do, and what it would read."""

    resolved: ResolvedPlan
    steps: list[StepPlan]
    compared_against: str | None

    @property
    def rerunning(self) -> int:
        return sum(1 for step in self.steps if step.rerunning)


def build_plan(
    *,
    pipeline: PipelineConfig,
    pipeline_hash: str,
    documents: dict[str, str],
    previous: ResolvedPlan | None,
    previous_id: str | None = None,
    prompt_hashes: Mapping[str, str] | None = None,
    schema_hashes: Mapping[str, str | None] | None = None,
    converters: Sequence[PinnedConverter] | None = None,
    reference: Mapping[str, str] | None = None,
) -> Plan:
    """Resolve the pipeline and say, per step, what would happen to it.

    `previous` is the resolved plan of the most recent run, or `None` when there
    has never been one. `prompt_hashes`, `schema_hashes` and `converters` are the
    same ones a run keys on, handed in by the same caller: a plan resolved
    without them would print `cached` for a prompt, or a converter version, a run
    is about to miss on (R4.12).
    """
    resolved = resolve(
        pipeline=pipeline,
        pipeline_hash=pipeline_hash,
        documents=documents,
        prompt_hashes=prompt_hashes,
        schema_hashes=schema_hashes,
        converters=converters,
        reference=reference,
    )
    return Plan(
        resolved=resolved,
        steps=diff(resolved, previous),
        compared_against=previous_id,
    )


def pinned_documents(rows) -> dict[str, str]:
    """The snapshot each live document is currently held at.

    Tombstoned rows are left out: a run plans over what is in scope now. A past
    run that pinned one keeps reading it, which is R4.9's business and is served
    from that run's own manifest rather than from here.
    """
    # `snapshot`, not `content_hash`: a plan pins bytes that exist, and for a
    # source declaring `fields` the normalised hash addresses none (R2.17).
    return {row.key: row.snapshot for row in rows if row.state is not State.TOMBSTONED}


def latest_manifest(
    runs: Path,
    pipeline: str,
    *,
    unreadable: list[tuple[str, str]] | None = None,
    stopped: list[str] | None = None,
) -> tuple[ResolvedPlan | None, str | None]:
    """The most recent run's resolved plan, or `(None, None)` if there is none.

    Run directories are named with a sortable timestamp prefix (spec 000), so
    the newest is the last by name -- no `stat` call, and no dependence on
    filesystem timestamps that a copy would rewrite. A newer manifest that
    cannot be read is passed over, and put in `unreadable` with why, for the
    command to name (R4.30).

    Given `stopped`, a run of the pipeline that wrote no `failures.json` is
    passed over too, and put in it. It stopped before it ended, or predates
    R4.27, and its manifest, written before anything was asked, promises
    answers it may never have cached: a plan compared against it printed
    `cached` for a step the next run asked again (R4.31).
    """
    if not runs.is_dir():
        return None, None

    for directory in sorted((path for path in runs.iterdir() if path.is_dir()), reverse=True):
        manifest = directory / MANIFEST_NAME
        if not manifest.is_file():
            continue
        # Read through the model that writes it, so a plan comparing against a
        # past run and a run recording this one cannot drift into two shapes of
        # the same file.
        found = read_manifest(manifest)
        if isinstance(found, str):
            # It says nothing of its run, not even its pipeline (R4.30).
            if unreadable is not None:
                unreadable.append((directory.name, found))
            continue
        if found.plan.pipeline != pipeline:
            continue
        if stopped is not None and not (directory / FAILURES_NAME).is_file():
            stopped.append(directory.name)
            continue
        return found.plan, directory.name

    return None, None
