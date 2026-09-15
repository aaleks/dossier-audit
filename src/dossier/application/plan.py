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

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.domain.pipeline import PipelineConfig
from dossier.domain.resolution import ResolvedPlan, ResolvedStep, resolve
from dossier.domain.sync import State


class StepStatus(Enum):
    """What `--plan` says would happen to one step (spec 004, "Plan diffing").

    Ordered by how much explaining each one needs, which is also the order they
    are checked in: a step whose prompt *and* inputs moved is reported as
    `inputs changed`, because that is the change that re-points the graph.
    """

    NEW = "new"
    INPUTS_CHANGED = "inputs changed"
    PROMPT_CHANGED = "prompt changed"
    UPSTREAM_CHANGED = "upstream changed"
    CACHED = "cached"


@dataclass(frozen=True)
class StepPlan:
    """One line of the plan, with the evidence behind it."""

    step: ResolvedStep
    status: StepStatus
    was: list[str] | None = None

    @property
    def rerunning(self) -> bool:
        return self.status is not StepStatus.CACHED


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
) -> Plan:
    """Resolve the pipeline and say, per step, what would happen to it.

    `previous` is the resolved plan of the most recent run, or `None` when there
    has never been one. Everything is `new` in that case, which is the honest
    answer rather than a cheerful one -- a first plan has nothing to compare
    against and should not imply otherwise.
    """
    resolved = resolve(
        pipeline=pipeline, pipeline_hash=pipeline_hash, documents=documents
    )
    return Plan(
        resolved=resolved,
        steps=_diff(resolved, previous),
        compared_against=previous_id,
    )


def _diff(resolved: ResolvedPlan, previous: ResolvedPlan | None) -> list[StepPlan]:
    """Per step: what changed, and what it was before.

    Upstream propagation is why this walks in declaration order and keeps a
    running set. A step whose own inputs and prompt are untouched must still
    re-run if anything it reads will, and that is a property of the whole chain
    above it rather than of the step itself.
    """
    if previous is None:
        return [StepPlan(step=step, status=StepStatus.NEW) for step in resolved.steps]

    before = {step.id: step for step in previous.steps}
    rerunning: set[str] = set()
    plans: list[StepPlan] = []

    # `prompt changed` is deliberately not decided here. The obvious shortcut --
    # comparing the pipeline hash -- is wrong, and R4.5 says so in as many words:
    # a comment added to pipeline.yaml changes that hash and must still leave
    # every step `cached`. Answering it properly needs a per-step prompt file
    # hash on the plan, which arrives with the slice that writes manifests.
    for step in resolved.steps:
        earlier = before.get(step.id)
        if earlier is None:
            status, was = StepStatus.NEW, None
        elif earlier.inputs != step.inputs:
            status, was = StepStatus.INPUTS_CHANGED, earlier.inputs
        elif rerunning.intersection(step.inputs):
            status, was = StepStatus.UPSTREAM_CHANGED, None
        else:
            status, was = StepStatus.CACHED, None

        if status is not StepStatus.CACHED:
            rerunning.add(step.id)
        plans.append(StepPlan(step=step, status=status, was=was))

    return plans


def pinned_documents(rows) -> dict[str, str]:
    """The snapshot each live document is currently held at.

    Tombstoned rows are left out: a run plans over what is in scope now. A past
    run that pinned one keeps reading it, which is R4.9's business and is served
    from that run's own manifest rather than from here.
    """
    # `snapshot`, not `content_hash`: a plan pins bytes that exist, and for a
    # source declaring `fields` the normalised hash addresses none (R2.17).
    return {row.key: row.snapshot for row in rows if row.state is not State.TOMBSTONED}


def latest_manifest(runs: Path, pipeline: str) -> tuple[ResolvedPlan | None, str | None]:
    """The most recent run's resolved plan, or `(None, None)` if there is none.

    Run directories are named with a sortable timestamp prefix (spec 000), so
    the newest is the last by name -- no `stat` call, and no dependence on
    filesystem timestamps that a copy would rewrite.
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
        found = Manifest.read(manifest)
        if found.plan.pipeline != pipeline:
            continue
        return found.plan, directory.name

    return None, None
