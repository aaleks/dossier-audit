"""What `--plan` says would happen to each step, from two resolved plans (spec 004).

A plan is a promise about a run: `cached` means the next run will serve that
step from the cache, and anything else means it will ask the model. The promise
holds only if the plan is keyed the way the run is, so the comparison here is
over exactly what enters a stage key -- the step's inputs, its prompt's hash and
its declaration's hash -- and over nothing else (R4.12). The pipeline hash is
deliberately not consulted: a comment added to `pipeline.yaml` moves it and
must still leave every step `cached` (R4.5).

Pure. Two resolved plans in, one line per step out.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from dossier.domain.resolution import ResolvedPlan, ResolvedStep


class StepStatus(Enum):
    """What `--plan` says would happen to one step (spec 004, "Plan diffing").

    Ordered by how much explaining each one needs, which is also the order they
    are checked in: a step whose prompt *and* inputs moved is reported as
    `inputs changed`, because that is the change that re-points the graph.
    """

    NEW = "new"
    INPUTS_CHANGED = "inputs changed"
    PROMPT_CHANGED = "prompt changed"
    DECLARATION_CHANGED = "declaration changed"
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


def diff(resolved: ResolvedPlan, previous: ResolvedPlan | None) -> list[StepPlan]:
    """Per step: what changed since `previous`, and what it was before (R4.12).

    Upstream propagation is why this walks in declaration order and keeps a
    running set. A step whose own inputs, prompt and declaration are untouched
    must still re-run if anything it reads will, and that is a property of the
    whole chain above it rather than of the step itself.

    Everything is `new` when there is no previous plan, which is the honest
    answer rather than a cheerful one: a first plan has nothing to compare
    against and should not imply otherwise.
    """
    if previous is None:
        return [StepPlan(step=step, status=StepStatus.NEW) for step in resolved.steps]

    before = {step.id: step for step in previous.steps}
    rerunning: set[str] = set()
    plans: list[StepPlan] = []

    for step in resolved.steps:
        earlier = before.get(step.id)
        if earlier is None:
            status, was = StepStatus.NEW, None
        elif earlier.inputs != step.inputs:
            status, was = StepStatus.INPUTS_CHANGED, earlier.inputs
        elif earlier.prompt_hash != step.prompt_hash:
            status, was = StepStatus.PROMPT_CHANGED, None
        elif earlier.schema_hash != step.schema_hash:
            status, was = StepStatus.DECLARATION_CHANGED, None
        elif rerunning.intersection(step.inputs):
            status, was = StepStatus.UPSTREAM_CHANGED, None
        else:
            status, was = StepStatus.CACHED, None

        if status is not StepStatus.CACHED:
            rerunning.add(step.id)
        plans.append(StepPlan(step=step, status=status, was=was))

    return plans
