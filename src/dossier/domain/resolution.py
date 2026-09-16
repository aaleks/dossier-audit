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
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dossier.domain.pipeline import PipelineConfig, StepConfig, is_relative_reference

# Kept beside `is_relative_reference`, which decides *whether* a reference is
# sugar; this one reads the count out of it. One pattern, asked two questions.
_PREVIOUS = re.compile(r"^previous(?:\((?P<n>\d+)\))?$")


class ResolvedStep(BaseModel):
    """One step with every relative reference already expanded (R4.4).

    The prompt and schema hashes are here because spec 004 requires a manifest to
    record them, and because a replay needs them: they are two of the four things
    a stage key is composed of (spec 005), so a run that recorded only its inputs
    could not work out what it had already computed (R4.7).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    inputs: list[str]
    # How the step ran. Recorded because a replay has only the manifest, and a
    # step replayed in the wrong mode would look for artifacts that were never
    # written -- one per document where there is one for the corpus, or the
    # reverse (R4.7).
    mode: Literal["per_file", "aggregate"] = "per_file"
    prompt_hash: str = ""
    schema_hash: str | None = None
    # Recorded for the same reason as `schema_hash`: it is part of the stage key
    # (R6.12), and a replay has only the manifest to rebuild that key from.
    generated_schema_hash: str | None = None


class PinnedDocument(BaseModel):
    """One document as this run will read it: a key and the snapshot behind it.

    Pinned rather than looked up, because a run is defended by what it actually
    read. A newer snapshot arriving later does not change what this plan means
    (R4.9).
    """

    model_config = ConfigDict(frozen=True)

    key: str
    snapshot: str
    # What the connector said these bytes were, at the time of this run (R2.16).
    # Pinned here so a replay needs no ledger: the ledger describes what is held
    # today, and a re-synced source would otherwise change which converter a past
    # run appears to have used.
    media_type: str = ""


class PinnedConverter(BaseModel):
    """A converter as this run used it (spec 004, R8.2).

    Recorded so a run is reproducible without the installed packages agreeing,
    which is the difference between a manifest that describes a *run* and one
    that merely describes a pipeline. Raising a converter's version is the whole
    mechanism R5.4 rests on; a replay that adopted today's version would be
    reproducing today's tools rather than that afternoon's audit (R4.7, R4.9).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    media_type: str
    kind: str


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
    converters: list[PinnedConverter] = []


def previous_count(reference: str) -> int:
    """How many preceding steps a piece of sugar asks for.

    `previous` is `previous(1)`. They are the same reference written two ways,
    and giving them separate paths is how they drift apart.
    """
    match = _PREVIOUS.match(reference)
    if match is None:
        raise ValueError(f"{reference!r} is not a relative reference")
    return 1 if match.group("n") is None else int(match.group("n"))


def expand(
    steps: Sequence[StepConfig],
    *,
    prompt_hashes: Mapping[str, str] | None = None,
    schema_hashes: Mapping[str, str | None] | None = None,
    generated_schema_hashes: Mapping[str, str | None] | None = None,
) -> list[ResolvedStep]:
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
        resolved.append(
            ResolvedStep(
                id=step.id,
                inputs=inputs,
                mode=step.mode,
                prompt_hash=(prompt_hashes or {}).get(step.id, ""),
                schema_hash=(schema_hashes or {}).get(step.id),
                generated_schema_hash=(generated_schema_hashes or {}).get(step.id),
            )
        )
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
    media_types: Mapping[str, str] | None = None,
    prompt_hashes: Mapping[str, str] | None = None,
    schema_hashes: Mapping[str, str | None] | None = None,
    generated_schema_hashes: Mapping[str, str | None] | None = None,
    converters: Sequence[PinnedConverter] | None = None,
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
        steps=expand(
            pipeline.steps,
            prompt_hashes=prompt_hashes,
            schema_hashes=schema_hashes,
            generated_schema_hashes=generated_schema_hashes,
        ),
        documents=[
            PinnedDocument(
                key=key,
                snapshot=documents[key],
                media_type=(media_types or {}).get(key, ""),
            )
            for key in sorted(documents)
        ],
        # Sorted by the pair each claims, so two machines with the same
        # converters installed in a different order write the same manifest
        # (R4.8, R5.6).
        converters=sorted(converters or [], key=lambda c: (c.media_type, c.kind, c.id)),
    )


def validate_input_arity(steps: Sequence[StepConfig], resolved: Sequence[ResolvedStep]) -> None:
    """Every declared input must stand for exactly one resolved id (R4.1).

    `previous(2)` expands to two ids, which is correct and is what R4.2 says.
    What has no answer is how to *render* it: spec 003 puts multiple inputs under
    distinct labelled tags, which is a statement about declared inputs, and one
    placeholder cannot carry two values.

    So the expansion stays faithful and the refusal lives here, called during
    resolution. It was previously discovered inside the execution loop, which
    meant a pipeline it rejected had already written its manifest and already
    spent model calls on the steps above the offending one -- exactly the
    half-executed run R4.1 exists to make impossible.
    """
    for declared, expanded in zip(steps, resolved, strict=True):
        if len(declared.inputs) != len(expanded.inputs):
            raise ValueError(
                f"step {declared.id!r} declares {len(declared.inputs)} input(s) that "
                f"expand to {len(expanded.inputs)}. `previous(n)` for n > 1 has no "
                "agreed rendering: spec 003 puts multiple inputs under distinct "
                "labelled tags, and one placeholder cannot carry several."
            )


def run_id(started_at: datetime, suffix: str) -> str:
    """The identifier one run is filed under (R0.8, R0.7 example 4).

    ISO 8601 *basic* format, because a run id is a directory name and the
    extended form's colons are illegal on Windows -- found the hard way, by a
    manifest that could not be written. Still sorts lexicographically, which
    `plan.latest_manifest` depends on for "the newest is the last by name".

    The suffix separates two runs started in the same second. It is passed in
    rather than generated, because randomness belongs to the composition root.

    A naive or non-UTC timestamp is refused. `strftime` appends a literal `Z`
    whatever the tzinfo says, so a local time would be filed as if it were UTC --
    silently, and only visibly wrong when two machines' runs are sorted together.
    `infrastructure.ledger` already guards the same hazard; this is the other
    place it lives.
    """
    if started_at.tzinfo is None or started_at.utcoffset() != timedelta(0):
        raise ValueError(
            f"a run id needs a UTC timestamp; got {started_at!r}. `Z` is appended "
            "literally, so anything else would be filed as a time it was not."
        )
    return f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{suffix}"
