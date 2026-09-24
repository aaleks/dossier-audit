"""What `--plan` says would happen to each step, from two resolved plans (spec 004).

A plan is a promise about a run: `cached` means the next run will serve that
step from the cache, and anything else means it will ask the model. The promise
holds only if the plan is keyed the way the run is, so the comparison here is
over exactly what enters a stage key (spec 005) and over nothing else (R4.12):

- the step's inputs, its prompt's hash and its declaration's hash -- what a
  person edits under `pipelines/`;
- the pinned model identifier (R5.3);
- the converted text of every document the step reads, which moves when a
  snapshot moves or when the converter that reads it does (R5.4, R5.7).

The last three were missing until R4.12's status list grew to hold them, and
their absence was the rule's own failure one level out: changing `model:`
printed `cached` and then asked the model for every document.

The pipeline hash is deliberately not consulted: a comment added to
`pipeline.yaml` moves it and must still leave every step `cached` (R4.5). Nor is
anything about where a model is served, which is in no key (R9.2).

Pure. Two resolved plans in, one line per step out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from dossier.domain.pipeline import SOURCE_KEYWORDS
from dossier.domain.resolution import PinnedDocument, ResolvedPlan, ResolvedStep


class StepStatus(Enum):
    """What `--plan` says would happen to one step (spec 004, "Plan diffing").

    Ordered by how much explaining each one needs, which is also the order they
    are checked in: a step whose prompt *and* inputs moved is reported as
    `inputs changed`, because that is the change that re-points the graph, and
    one whose model *and* documents moved is reported as `model changed`,
    because that is the change affecting every document rather than some.
    """

    NEW = "new"
    INPUTS_CHANGED = "inputs changed"
    PROMPT_CHANGED = "prompt changed"
    DECLARATION_CHANGED = "declaration changed"
    MODEL_CHANGED = "model changed"
    CONVERTERS_CHANGED = "converters changed"
    DOCUMENTS_CHANGED = "documents changed"
    UPSTREAM_CHANGED = "upstream changed"
    CACHED = "cached"


@dataclass(frozen=True)
class StepPlan:
    """One line of the plan, with the evidence behind it."""

    step: ResolvedStep
    status: StepStatus
    was: list[str] | None = None
    # Which documents this step would re-ask for, as `<key> new` or
    # `<key> changed`. Named rather than counted: "3 documents changed" in a
    # corpus of four thousand is a number nobody can act on, and the keys are
    # what a person checks against their own source.
    moved: tuple[str, ...] = ()

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
    # Worked out once rather than per step: both answer for the whole plan, and
    # asking four thousand documents the same question once per step is the sort
    # of thing that makes `--plan` slower than the run it describes.
    converters_moved = _converters_moved(previous, resolved)
    moved_documents = _moved(previous.documents, resolved.documents)

    rerunning: set[str] = set()
    plans: list[StepPlan] = []

    for step in resolved.steps:
        earlier = before.get(step.id)
        reads_documents = bool(SOURCE_KEYWORDS.intersection(step.inputs))
        moved: tuple[str, ...] = ()
        if earlier is None:
            status, was = StepStatus.NEW, None
        elif earlier.inputs != step.inputs:
            status, was = StepStatus.INPUTS_CHANGED, earlier.inputs
        elif earlier.prompt_hash != step.prompt_hash:
            status, was = StepStatus.PROMPT_CHANGED, None
        elif earlier.schema_hash != step.schema_hash:
            status, was = StepStatus.DECLARATION_CHANGED, None
        elif previous.model_of(earlier) != resolved.model_of(step):
            # Whatever the step reads: the model it is asked with is in its
            # stage key, so none of its documents is served from the cache. Per
            # step, because a step may name its own (R3.14): the pipeline's
            # moving leaves such a step where it was (R5.13).
            status, was = StepStatus.MODEL_CHANGED, None
        elif converters_moved and reads_documents:
            # Only the steps reading a source. A step reading another step's
            # output is reached by upstream propagation, if at all -- the
            # converted text is not its input.
            status, was = StepStatus.CONVERTERS_CHANGED, None
        elif moved_documents and reads_documents:
            status, was, moved = StepStatus.DOCUMENTS_CHANGED, None, moved_documents
        elif rerunning.intersection(step.inputs):
            status, was = StepStatus.UPSTREAM_CHANGED, None
        else:
            status, was = StepStatus.CACHED, None

        if status is not StepStatus.CACHED:
            rerunning.add(step.id)
        plans.append(StepPlan(step=step, status=status, was=was, moved=moved))

    return plans


def _converters_moved(previous: ResolvedPlan, resolved: ResolvedPlan) -> bool:
    """Whether the converters behind the converted text have changed (R5.4).

    A side that pinned none has said nothing, and absence is not a different
    converter: a manifest written before converters were recorded, or by a
    caller that does not pin them, cannot be evidence of a change. Comparing
    against it would report `converters changed` on every plan forever, which is
    the noise that makes a plan worth ignoring -- and a plan nobody reads is
    worse than one that is occasionally silent.

    The distinction is the one the gold set draws between `null` and absent
    (R7.3): not stated is its own answer, and it is not "no".
    """
    if not previous.converters or not resolved.converters:
        return False
    return _converters(previous) != _converters(resolved)


def _converters(plan: ResolvedPlan) -> tuple[tuple[str, str, str, str], ...]:
    """The converters a plan pins, in a stable order, as comparable tuples.

    Sorted, because a converter's position in the list is an installation detail
    and re-ordering two packages has not changed what any of them produces
    (R5.6). The id and the version are what a convert key holds; the pair each
    one claims travels with them because two converters swapping pairs would
    change which one reads a document without either version moving (R8.3).
    """
    return tuple(sorted((c.id, c.version, c.media_type, c.kind) for c in plan.converters))


def _moved(previous: list[PinnedDocument], resolved: list[PinnedDocument]) -> tuple[str, ...]:
    """The documents a run would have to ask about again, in key order (R4.12).

    Added or re-snapshotted, never departed. A document that has left the source
    is strictly less work: every key that remains is the key it was, so a
    shrinking corpus is `cached` and reporting it as a change would send someone
    looking for an edit that never happened.
    """
    held = {document.key: document.snapshot for document in previous}
    return tuple(
        f"{document.key} {'changed' if document.key in held else 'new'}"
        for document in sorted(resolved, key=lambda d: d.key)
        if held.get(document.key) != document.snapshot
    )


def changed_steps(plans: Sequence[StepPlan]) -> str:
    """The steps that differ between two runs, as one line (R11.13).

    What `diff` already decided, written the way a tag can hold it: the cause of
    a delta belongs on the same page as the delta, and until now it was in
    neither compared run's record.

    In declaration order, which is the order `diff` walks and the order a person
    reads a pipeline in. Nothing here enters a key (R10.4), so any order would
    break no rule -- and a line whose order moved between two comparisons of one
    change would read as two different findings.

    Empty when nothing moved. The caller records that as a present and empty tag,
    because an absent one is indistinguishable from a comparison recorded before
    this rule existed (R11.9 row 3).
    """
    return ", ".join(
        f"{plan.step.id} ({plan.status.value})" for plan in plans if plan.rerunning
    )
