"""Turning a pipeline as written into a pipeline as run (spec 004).

Relative references make configuration pleasant to write and dangerous to
execute: `input: previous` means something different the moment a step is
inserted above it, and nothing in the YAML shows that it moved. This module
expands them once, before any work starts, so that everything downstream reads
concrete ids and the word `previous` does not survive into a manifest (R4.4).

Pure decisions only. No clock, no filesystem, no run id -- what is here can be
checked with a list of steps in hand, which is what makes R4.2, R4.3 and R4.8
provable in milliseconds.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from dossier.domain.pipeline import PipelineConfig, StepConfig, is_relative_reference

# Kept beside `is_relative_reference`, which decides *whether* a reference is
# sugar; this one reads the count out of it. One pattern, asked two questions.
_PREVIOUS = re.compile(r"^previous(?:\((?P<n>\d+)\))?$")


class ResolvedStep(BaseModel):
    """One step with every relative reference already expanded (R4.4)."""

    model_config = ConfigDict(frozen=True)

    id: str
    inputs: list[str]


class PinnedDocument(BaseModel):
    """One document as this run will read it: a key and the snapshot behind it.

    Pinned rather than looked up, because a run is defended by what it actually
    read. A newer snapshot arriving later does not change what this plan means
    (R4.9).
    """

    model_config = ConfigDict(frozen=True)

    key: str
    snapshot: str


class ResolvedPlan(BaseModel):
    """A pipeline resolved against a set of snapshots -- and nothing else.

    Deliberately carries no run id and no start time. Those are the only two
    things a manifest records about *when* rather than *what*, and keeping them
    out of this model is what makes R4.8 true by construction instead of true by
    remembering to exclude two fields at every comparison.

    `dossier.application` wraps this with the run metadata on the way to
    `runs/<run_id>/manifest.json`.
    """

    model_config = ConfigDict(frozen=True)

    pipeline: str
    pipeline_hash: str
    model: str
    steps: list[ResolvedStep]
    documents: list[PinnedDocument]


def previous_count(reference: str) -> int:
    """How many preceding steps a piece of sugar asks for.

    `previous` is `previous(1)`. They are the same reference written two ways,
    and giving them separate paths is how they drift apart.
    """
    match = _PREVIOUS.match(reference)
    if match is None:
        raise ValueError(f"{reference!r} is not a relative reference")
    return 1 if match.group("n") is None else int(match.group("n"))


def expand(steps: Sequence[StepConfig]) -> list[ResolvedStep]:
    """Every step's inputs, with `previous` replaced by the ids it stands for.

    Declaration order throughout: the ids a step reaches back to are returned in
    the order they were declared, not the order they were asked for, so two
    pipelines that resolve to the same graph serialise identically (R4.8).
    """
    resolved: list[ResolvedStep] = []
    declared: list[str] = []

    for step in steps:
        inputs: list[str] = []
        for reference in step.inputs:
            if is_relative_reference(reference):
                inputs.extend(_preceding(step.id, declared, previous_count(reference)))
            else:
                inputs.append(reference)
        resolved.append(ResolvedStep(id=step.id, inputs=inputs))
        declared.append(step.id)

    return resolved


def _preceding(step_id: str, declared: Sequence[str], count: int) -> list[str]:
    """The `count` ids declared immediately before this step, in that order.

    Checked rather than sliced (R4.3). `declared[-2:]` on a one-element list
    returns one element and raises nothing, so a step asking for two preceding
    steps when only one exists would run with an input list its author never
    wrote -- and the pipeline would look fine.
    """
    if count > len(declared):
        available = (
            "it has no preceding step"
            if not declared
            else f"only {len(declared)} step(s) precede it"
        )
        raise ValueError(
            f"step {step_id!r} asks for {count} preceding step(s), but {available}. "
            f"Declared before it: {list(declared) or 'nothing'}."
        )
    return list(declared[len(declared) - count :])


def resolve(
    *,
    pipeline: PipelineConfig,
    pipeline_hash: str,
    documents: Mapping[str, str],
) -> ResolvedPlan:
    """A pipeline and a set of snapshots, frozen into one plan (R4.4, R4.8).

    Every argument is passed in: this layer has no filesystem to read the
    pipeline hash from and no ledger to ask which snapshots are current. That is
    what lets the same function answer for a live workspace and for a replay
    three years later (R4.7).

    Documents are sorted by key. A mapping's iteration order is its insertion
    order, and insertion order here comes from a ledger query -- so sorting is
    what stops the plan depending on how the rows happened to come back (R0.4,
    R5.6).
    """
    return ResolvedPlan(
        pipeline=pipeline.name,
        pipeline_hash=pipeline_hash,
        model=pipeline.model,
        steps=expand(pipeline.steps),
        documents=[
            PinnedDocument(key=key, snapshot=documents[key]) for key in sorted(documents)
        ],
    )
