"""R5.13 — a stage key holds the model its step is asked with, so changing a
model moves only the keys of the steps asked with it.

Reclaimed from R5.3's test, which it replaces: R5.3 said changing the model
identifier changes every stage key, and that stopped being true once a step
could name its own model (R3.14) and keep it while the pipeline's moved. Its
rows are kept here, because each is still true of a pipeline whose steps name
no model -- which is every pipeline written before R3.14 -- and the rows about
a step's own model are added beside them.

The key is composed from the model `ResolvedPlan.model_of` gives each step, the
one answer the run, `--plan` and `--replay` all ask (R3.14). Every other input
is held fixed, so a key that moves moved because of its model.

This is what makes `--compare` a fair test (R7.8): swapping a pin and finding
half the steps it answers served from cache would compare one model's answers
against another's, and report the difference as a regression in whichever ran
second.
"""

from __future__ import annotations

from dossier.domain.keys import ArtifactInput, ConvertInputs, StageInputs, cache_key
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.resolution import PinnedDocument, ResolvedPlan, ResolvedStep, resolve

PINNED = "anthropic:claude-sonnet-4-5-20250929"
OTHER = "anthropic:claude-opus-4-1-20250805"
EXTRACT_MODEL = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
REVISED_MODEL = "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5
STEPS = ("extract", "verify", "report")

PROMPT = ArtifactInput(role="prompt", path="prompts/02_verify.md", hash="0e52dd18" * 8)
SCHEMA = ArtifactInput(role="schema", path="schemas/incident.json", hash="b81f0c6d" * 8)
CONVERTED = ArtifactInput(role="documents", path="converted/INC-4821.md", hash="5d3ba0f7" * 8)


def stage(step: str, model: str) -> StageInputs:
    return StageInputs(
        step=step, prompt=PROMPT, output_schema=SCHEMA, model=model, inputs=[CONVERTED]
    )


def conversion(version: str = "1.3.0") -> ConvertInputs:
    return ConvertInputs(
        snapshot="a3f9c1e2" * 8, converter_id="pdf-markdown", converter_version=version
    )


def _plan(model: str = PINNED, *, extract_model: str | None = None) -> ResolvedPlan:
    """`extract` -> `verify` -> `report`, `extract` naming `extract_model` if given."""
    return ResolvedPlan(
        pipeline="incident-audit",
        pipeline_hash="6e0d4b27" * 8,
        model=model,
        steps=[
            ResolvedStep(id="extract", inputs=["documents"], model=extract_model),
            ResolvedStep(id="verify", inputs=["documents", "extract"]),
            ResolvedStep(id="report", inputs=["verify"], mode="aggregate"),
        ],
        documents=[PinnedDocument(key="INC-4821", snapshot="a3f9c1e2" * 8)],
    )


def keys(plan: ResolvedPlan) -> dict[str, str]:
    """Each step's key, every input but its model held fixed."""
    return {step.id: cache_key(stage(step.id, plan.model_of(step))) for step in plan.steps}


def moved(before: ResolvedPlan, after: ResolvedPlan) -> set[str]:
    old, new = keys(before), keys(after)
    return {step for step in STEPS if old[step] != new[step]}


class TestAStageKeyHoldsTheModelItsStepIsAskedWith:
    """R5.13 — the model a step is asked with is in its key, and in no convert key."""

    def test_every_stage_key_moves_when_the_one_model_does(self):
        """Row 1: the pinned model replaced, no step naming its own (R5.3 row 1)."""
        for step in STEPS:
            assert cache_key(stage(step, PINNED)) != cache_key(stage(step, OTHER))
        assert moved(_plan(PINNED), _plan(OTHER)) == set(STEPS)

    def test_the_pipelines_model_moving_leaves_a_step_with_its_own(self):
        """Row 2: `extract` naming Ollama; the pipeline's `model:` replaced."""
        before = _plan(PINNED, extract_model=EXTRACT_MODEL)
        after = _plan(OTHER, extract_model=EXTRACT_MODEL)

        assert moved(before, after) == {"verify", "report"}

    def test_a_steps_own_model_moving_moves_that_step_alone(self):
        """Row 3: `extract`'s own model replaced; the others' own inputs held fixed.

        `verify` reads `extract`, so its key would move through `extract`'s
        output if that output changed (R5.2). Held fixed here, what is left is
        the claim about models: `verify` was not asked with `extract`'s.
        """
        before = _plan(extract_model=EXTRACT_MODEL)
        after = _plan(extract_model=REVISED_MODEL)

        assert moved(before, after) == {"extract"}

    def test_no_convert_key_moves(self):
        """Row 4: conversion does not involve a model (R5.3 row 2).

        A model change that re-converted would re-do work that could not
        possibly differ -- and, on a PDF corpus, that is the expensive half.
        """
        before = cache_key(conversion())
        _ = [cache_key(stage(step, OTHER)) for step in ("extract", "verify")]
        _ = keys(_plan(OTHER, extract_model=REVISED_MODEL))

        assert cache_key(conversion()) == before

    def test_the_same_pin_leaves_every_key_alone(self):
        """Row 5, a counter-example: the same model through another endpoint (R5.3 row 4).

        The rule is about the identifier, not about how the model was reached.
        There is nowhere in `StageInputs` to put an endpoint, which is the
        strongest form this guarantee can take (R5.1 example 3).
        """
        assert cache_key(stage("verify", PINNED)) == cache_key(stage("report", PINNED))
        assert "endpoint" not in StageInputs.model_fields, (
            "and there is nowhere to record one, which is the stronger claim"
        )

    def test_naming_the_pipelines_own_model_is_the_key_of_naming_none(self):
        """Row 6, a counter-example: `verify` naming the pipeline's model resolves as none."""

        def resolved(verify_model: str | None) -> ResolvedPlan:
            return resolve(
                pipeline=PipelineConfig(
                    name="incident-audit",
                    sources=["incidents"],
                    model=PINNED,
                    steps=[
                        StepConfig(
                            id="extract",
                            prompt="prompts/extract.md",
                            input="documents",
                            mode="per_file",
                            model=EXTRACT_MODEL,
                        ),
                        StepConfig(
                            id="verify",
                            prompt="prompts/verify.md",
                            input=["documents", "extract"],
                            mode="per_file",
                            model=verify_model,
                        ),
                    ],
                ),
                pipeline_hash="6e0d4b27" * 8,
                documents={"INC-4821": "a3f9c1e2" * 8},
            )

        assert keys(resolved(PINNED)) == keys(resolved(None))

    def test_two_different_pins_of_the_same_family_still_differ(self):
        """The one where a version bump is a different model (R5.3).

        `claude-sonnet-4-5-20250929` and a later dated pin are different models
        for this purpose, whatever their family. R0.6 forbids floating aliases
        precisely so that this comparison is exact.
        """
        later = "anthropic:claude-sonnet-4-5-20260101"

        assert cache_key(stage("verify", PINNED)) != cache_key(stage("verify", later))
