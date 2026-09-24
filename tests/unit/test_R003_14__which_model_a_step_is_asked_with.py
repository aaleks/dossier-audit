"""R3.14 — a step may name its own `model`, and is asked with it; a step that
names none is asked with the pipeline's.

The decisions, without a workspace: which model a resolved step is asked with,
what the manifest records of it, and what `--plan` concludes when one moves.
Plans are built directly, as R4.12's are, so each row is one comparison.
"""

from __future__ import annotations

import json

from dossier.domain.plan import StepStatus, diff
from dossier.domain.resolution import PinnedDocument, ResolvedPlan, ResolvedStep

PIPELINE_MODEL = "anthropic:claude-sonnet-4-5-20250929"
EXTRACT_MODEL = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
REVISED_MODEL = "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5
OTHER_PIPELINE_MODEL = "openai:gpt-4o-2024-08-06"
PROMPT = "0e52dd18" * 8
DECLARATION = "b81f0c6d" * 8


def _plan(*, model: str = PIPELINE_MODEL, extract_model: str | None = EXTRACT_MODEL):
    """`extract` -> `verify`, `extract` asked with its own model unless told otherwise."""
    return ResolvedPlan(
        pipeline="incident-audit",
        pipeline_hash="6e0d4b27" * 8,
        model=model,
        steps=[
            ResolvedStep(
                id="extract",
                inputs=["documents"],
                prompt_hash=PROMPT,
                schema_hash=DECLARATION,
                model=extract_model,
            ),
            ResolvedStep(
                id="verify",
                inputs=["documents", "extract"],
                prompt_hash=PROMPT,
                schema_hash=DECLARATION,
            ),
        ],
        documents=[PinnedDocument(key="INC-4821.md", snapshot="a3f9c1e2" * 8)],
    )


def _statuses(resolved: ResolvedPlan, previous: ResolvedPlan) -> dict[str, StepStatus]:
    return {plan.step.id: plan.status for plan in diff(resolved, previous)}


class TestTheResolvedPlanNamesEachStepsModel:
    """R3.14 — which model each resolved step is asked with, and what is written of it."""

    def test_a_step_with_its_own_model_is_asked_with_it(self):
        """Row 1: `extract` names Ollama, `verify` names none."""
        plan = _plan()
        extract, verify = plan.steps

        assert plan.model_of(extract) == EXTRACT_MODEL
        assert plan.model_of(verify) == PIPELINE_MODEL

    def test_the_manifest_records_a_steps_own_model_and_no_other(self):
        """Row 2: `extract` carries its model, `verify` none, the plan the pipeline's."""
        written = json.loads(_plan().model_dump_json())

        steps = {step["id"]: step for step in written["steps"]}
        assert steps["extract"]["model"] == EXTRACT_MODEL
        assert "model" not in steps["verify"]
        assert written["model"] == PIPELINE_MODEL

    def test_a_plan_whose_steps_name_none_writes_what_it_wrote_before(self):
        """Row 8, a counter-example: no step carries `model` -- not even `null`.

        A `"model": null` on every step would be a new manifest for every
        pipeline written before R3.14, though not one of them changed.
        """
        written = _plan(extract_model=None).model_dump_json(indent=2)

        assert '"model": null' not in written
        assert all("model" not in step for step in json.loads(written)["steps"])

    def test_a_manifest_written_before_reads_every_step_as_the_pipelines(self):
        """Row 8's other side: a manifest with no step `model` read back (R4.9)."""
        written = json.loads(_plan(extract_model=None).model_dump_json())

        read = ResolvedPlan.model_validate(written)

        assert [read.model_of(step) for step in read.steps] == [PIPELINE_MODEL] * 2
        assert read == _plan(extract_model=None)

    def test_a_steps_own_model_survives_the_round_trip(self):
        """Row 6's precondition: a replay reads back the model a step recorded."""
        read = ResolvedPlan.model_validate(json.loads(_plan().model_dump_json()))

        assert read.model_of(read.steps[0]) == EXTRACT_MODEL


class TestThePlanComparesEachStepsModel:
    """R3.14 rows 4 and 5 — `--plan` compares each step with the model it ran with."""

    def test_a_steps_own_model_moving_reruns_it_and_what_reads_it(self):
        """Row 4: `extract`'s model changed; `verify` reads `extract`."""
        statuses = _statuses(_plan(extract_model=REVISED_MODEL), _plan())

        assert statuses == {
            "extract": StepStatus.MODEL_CHANGED,
            "verify": StepStatus.UPSTREAM_CHANGED,
        }

    def test_the_pipelines_model_moving_reruns_only_the_steps_asked_with_it(self):
        """Row 5: the pipeline's `model:` changed, `extract` still naming its own."""
        statuses = _statuses(_plan(model=OTHER_PIPELINE_MODEL), _plan())

        assert statuses == {"extract": StepStatus.CACHED, "verify": StepStatus.MODEL_CHANGED}

    def test_a_step_given_its_own_model_since_the_last_run_is_rerun(self):
        """Row 4's boundary: `extract` named none last time and names Ollama now."""
        statuses = _statuses(_plan(), _plan(extract_model=None))

        assert statuses["extract"] is StepStatus.MODEL_CHANGED

    def test_the_same_models_written_differently_are_cached(self):
        """Row 7, at the plan: the pipeline's model, recorded as none, is the same model."""
        statuses = _statuses(_plan(extract_model=None), _plan(extract_model=None))

        assert statuses == {"extract": StepStatus.CACHED, "verify": StepStatus.CACHED}

    def test_every_step_reruns_when_the_one_model_moves(self):
        """Row 8, at the plan: no step names a model, so a new pin moves them all (R4.12)."""
        statuses = _statuses(
            _plan(model=OTHER_PIPELINE_MODEL, extract_model=None), _plan(extract_model=None)
        )

        assert statuses == {
            "extract": StepStatus.MODEL_CHANGED,
            "verify": StepStatus.MODEL_CHANGED,
        }
