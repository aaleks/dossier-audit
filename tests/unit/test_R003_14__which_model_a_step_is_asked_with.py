"""R3.14 — a step may name its own `model`, and is asked with it; a step that
names none is asked with the pipeline's.

The decisions, without a workspace: which model a resolved step is asked with,
what the manifest records of it, and what `--plan` concludes when one moves.
Plans are built directly, as R4.12's are, so each row is one comparison.

Then the wiring, a layer at a time: the loader holding a step's model to what
the pipeline's is held to, resolution recording it only where it differs, and
`execute` asking each step with its own model's client.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for, write_pipeline
from tests.scoring_example import ISSUES

from dossier.application.run import execute
from dossier.config.load import ConfigError, load_pipeline
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.plan import StepStatus, diff
from dossier.domain.resolution import PinnedDocument, ResolvedPlan, ResolvedStep, resolve

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


PROVIDERS = frozenset({"anthropic", "gemini", "hf", "ollama", "openai"})


def _written(root: Path, **step_models: str) -> Path:
    """`extract` -> `verify` in `pipeline.yaml`, each step naming the model given for it."""
    return write_pipeline(
        root,
        steps=["extract", "verify"],
        inputs={"verify": "[documents, extract]"},
        model=PIPELINE_MODEL,
        step_models=step_models,
    )


class TestAStepsModelIsCheckedAtLoadTime:
    """R3.14 rows 9 and 10 — held to what the pipeline's `model:` is held to."""

    def test_a_pinned_step_model_is_accepted(self, tmp_path: Path):
        """Row 1's configuration: `extract` naming Ollama by its digest."""
        pipeline = load_pipeline(_written(tmp_path, extract=EXTRACT_MODEL), providers=PROVIDERS)

        assert [step.model for step in pipeline.steps] == [EXTRACT_MODEL, None]
        assert pipeline.model == PIPELINE_MODEL

    def test_an_unpinned_step_model_is_refused_naming_where(self, tmp_path: Path):
        """Row 9: the alias `anthropic:claude-sonnet-4-5`, named with its line and key."""
        path = _written(tmp_path, extract="anthropic:claude-sonnet-4-5")
        line = (
            path.read_text(encoding="utf-8")
            .splitlines()
            .index("    model: anthropic:claude-sonnet-4-5")
        )

        with pytest.raises(ConfigError) as refused:
            load_pipeline(path, providers=PROVIDERS)

        said = str(refused.value)
        assert said.startswith(f"pipeline.yaml, line {line + 1}: steps.0.model ")
        assert "'anthropic:claude-sonnet-4-5' is a floating alias" in said

    def test_a_step_model_no_package_provides_is_refused_naming_those_that_do(
        self, tmp_path: Path
    ):
        """Row 10: `mistral:mistral-large-2411`, which nothing installed provides."""
        path = _written(tmp_path, verify="mistral:mistral-large-2411")

        with pytest.raises(ConfigError) as refused:
            load_pipeline(path, providers=PROVIDERS)

        said = str(refused.value)
        assert "steps.1.model 'mistral:mistral-large-2411' names provider 'mistral'" in said
        assert said.endswith("Available: anthropic, gemini, hf, ollama, openai")


def _resolved(**step_models: str) -> ResolvedPlan:
    """`extract` -> `verify` resolved over one document, each naming the model given."""
    steps = [
        StepConfig(
            id="extract",
            prompt="prompts/extract.md",
            input="documents",
            mode="per_file",
            model=step_models.get("extract"),
        ),
        StepConfig(
            id="verify",
            prompt="prompts/verify.md",
            input=["documents", "extract"],
            mode="per_file",
            model=step_models.get("verify"),
        ),
    ]
    return resolve(
        pipeline=PipelineConfig(
            name="incident-audit", sources=["incidents"], model=PIPELINE_MODEL, steps=steps
        ),
        pipeline_hash="6e0d4b27" * 8,
        documents={"INC-4821.md": "a3f9c1e2" * 8},
    )


class TestResolutionRecordsAStepsOwnModel:
    """R3.14 rows 2 and 7 — what resolution writes of a step's model."""

    def test_a_steps_own_model_is_recorded(self):
        """Row 2: `extract`'s own model on its resolved step, none on `verify`'s."""
        plan = _resolved(extract=EXTRACT_MODEL)

        assert [step.model for step in plan.steps] == [EXTRACT_MODEL, None]

    def test_naming_the_pipelines_own_model_resolves_as_naming_none(self):
        """Row 7: `verify` naming the pipeline's model is the plan of naming none."""
        assert _resolved(extract=EXTRACT_MODEL, verify=PIPELINE_MODEL) == _resolved(
            extract=EXTRACT_MODEL
        )


def _abstains(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {"field": "loss_amount", "value": None, "reason": "not stated in document"}
            ],
        }
    )


def _execute(workspace: Path, *, default, models, extract_model: str | None = EXTRACT_MODEL):
    """`extract` -> `verify` over `INC-4821`, `extract` naming `extract_model`."""
    from dossier.infrastructure.cache import ArtifactCache

    declared = OutputSchema(schema={"type": "object"}, declaration_hash="d24c86e1" * 8)
    return execute(
        workspace=workspace,
        pipeline=PipelineConfig(
            name="incident-audit",
            sources=["incidents-jira"],
            model=PIPELINE_MODEL,
            steps=[
                StepConfig(
                    id="extract",
                    prompt="prompts/extract.md",
                    input="documents",
                    mode="per_file",
                    output="schemas/incident.yaml",
                    model=extract_model,
                ),
                StepConfig(
                    id="verify",
                    prompt="prompts/verify.md",
                    input=["documents", "extract"],
                    mode="per_file",
                    output="schemas/incident.yaml",
                ),
            ],
        ),
        pipeline_hash="6e0d4b27" * 8,
        documents={"INC-4821": "a3f9c1e2" * 8},
        document_text={"INC-4821": ISSUES["INC-4821"]},
        schemas={"extract": declared, "verify": declared},
        prompts={
            "extract": prompt_for(["documents"]),
            "verify": prompt_for(["documents", "extract"]),
        },
        model=default,
        models=models,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )


class TestARunAsksEachStepWithItsModel:
    """R3.14 row 1 — `execute` asks each step with its own model's client."""

    def test_each_step_is_asked_by_its_models_client_and_keyed_under_it(self, tmp_path: Path):
        """Row 1: `extract` by the Ollama client, `verify` by the pipeline's."""
        own = FakeModelClient(responses=[_abstains("INC-4821")], model_id=EXTRACT_MODEL)
        default = FakeModelClient(responses=[_abstains("INC-4821")], model_id=PIPELINE_MODEL)

        _execute(tmp_path, default=default, models={EXTRACT_MODEL: own})

        assert (own.call_count, default.call_count) == (1, 1)
        run = tmp_path / "runs" / "20260806T142203Z-4f1a"
        for step, model in (("extract", EXTRACT_MODEL), ("verify", PIPELINE_MODEL)):
            (record,) = (run / step).glob("*.meta.json")
            assert json.loads(record.read_text(encoding="utf-8"))["model"] == model

    def test_a_step_whose_model_has_no_client_stops_the_run_before_any_call(
        self, tmp_path: Path
    ):
        """Row 1's precondition: a model a step names with no client stops everything."""
        default = FakeModelClient(responses=[], model_id=PIPELINE_MODEL)

        with pytest.raises(ValueError, match=r"extract.*ollama:qwen2\.5:7b"):
            _execute(tmp_path, default=default, models={})

        assert default.call_count == 0
        assert not (tmp_path / "runs").exists()

    def test_a_pipeline_whose_steps_name_none_needs_no_other_client(self, tmp_path: Path):
        """Row 8, a counter-example: one client, as before, and no `models` at all."""
        default = FakeModelClient(
            responses=[_abstains("INC-4821"), _abstains("INC-4821")], model_id=PIPELINE_MODEL
        )

        _execute(tmp_path, default=default, models=None, extract_model=None)

        assert default.call_count == 2


class TestTheJudgeIsThePipelinesModel:
    """R3.14 row 11 — a step's own model answers that step and judges nothing."""

    def test_an_eval_judges_with_the_pipelines_model(self, tmp_path: Path):
        """Row 11, a counter-example: `dossier eval`'s judge, over a pipeline whose
        `extract` names its own model."""
        from dossier.cli.main import _judging

        path = _written(tmp_path, extract=EXTRACT_MODEL)
        pipeline = load_pipeline(path, providers=PROVIDERS)

        judging = _judging(
            tmp_path,
            config=pipeline,
            pipeline_dir=path.parent,
            declaration=path.parent / "schemas" / "incident.yaml",
            documents={},
            withheld={},
            run_id="20260806T142203Z-4f1a",
        )

        assert judging.judge_model == PIPELINE_MODEL
        assert judging.model.model_id == PIPELINE_MODEL
