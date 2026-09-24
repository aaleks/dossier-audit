"""R11.22 — a run's record, and the pipeline version it built, name the model
each step was asked with.

The params are one function over the plan (R11.18): the run's record, the
eval's and the pipeline version's all read `version_params`, and the version
hash is taken over it (R13.1). So the rows are proved there, on plans built
directly, and then once each through the run and the eval that call it.

Row 5 pins a version hash as a literal. It is the hash this plan had before a
step could name a model, computed before this rule's code existed, and a
pipeline naming none must keep it: a new hash would register every existing
pipeline in the Models tab as a new version, though nothing about it changed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient, FakeTracker
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.eval import start_eval
from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.resolution import PinnedDocument, ResolvedPlan, ResolvedStep
from dossier.domain.tracking import version_params
from dossier.domain.versions import version_record

PIPELINE_MODEL = "anthropic:claude-sonnet-4-5-20250929"
EXTRACT_MODEL = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
REVISED_MODEL = "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5
# This file's plan with no step model, hashed by the code before R11.22.
VERSION_WITHOUT_STEP_MODELS = "9e996b1c9306aa86a75ef408188b6076cea852239a8e174e8a95ddd36fbe8f88"


def _plan(extract_model: str | None = EXTRACT_MODEL) -> ResolvedPlan:
    """`extract` -> `verify`, `extract` asked with its own model unless told otherwise."""
    return ResolvedPlan(
        pipeline="incident-audit",
        pipeline_hash="6e0d4b27" * 8,
        model=PIPELINE_MODEL,
        steps=[
            ResolvedStep(
                id="extract",
                inputs=["documents"],
                prompt_hash="0e52dd18" * 8,
                schema_hash="b81f0c6d" * 8,
                model=extract_model,
            ),
            ResolvedStep(
                id="verify",
                inputs=["documents", "extract"],
                prompt_hash="35d1a8ef" * 8,
                schema_hash="b81f0c6d" * 8,
            ),
        ],
        documents=[PinnedDocument(key="INC-4821", snapshot="a3f9c1e2" * 8)],
    )


def _version_hash(plan: ResolvedPlan) -> str:
    return version_record(plan).params["version_hash"]


class TestTheParamsNameEachStepsOwnModel:
    """R11.22 — `model/<step>` beside `prompt/<step>`, for a step with its own model."""

    def test_a_steps_own_model_is_a_param_and_no_other_step_gets_one(self):
        """Row 1, on the params: `model/extract`, and no `model/verify`."""
        params = version_params(_plan())

        assert params["model/extract"] == EXTRACT_MODEL
        assert "model/verify" not in params

    def test_the_version_carries_it_and_is_another_version(self):
        """Row 2: the version's params carry it, and its hash is not the plain pipeline's."""
        record = version_record(_plan())

        assert record.params["model/extract"] == EXTRACT_MODEL
        assert record.params["model"] == PIPELINE_MODEL
        assert _version_hash(_plan()) != _version_hash(_plan(extract_model=None))

    def test_a_steps_model_moving_moves_the_version(self):
        """Row 3: `extract` on `hf:...` instead: the pipeline's model and prompts unmoved."""
        before, after = version_record(_plan()), version_record(_plan(REVISED_MODEL))

        assert after.params["model"] == before.params["model"]
        assert after.params["prompt/extract"] == before.params["prompt/extract"]
        assert after.params["version_hash"] != before.params["version_hash"]

    def test_a_pipeline_whose_steps_name_none_records_what_it_recorded_before(self):
        """Row 5, a counter-example: no `model/` param, and the version hash unmoved."""
        plan = _plan(extract_model=None)

        assert not [name for name in version_params(plan) if name.startswith("model/")]
        assert _version_hash(plan) == VERSION_WITHOUT_STEP_MODELS


def _abstains(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {"field": "loss_amount", "value": None, "reason": "not stated in document"}
            ],
        }
    )


class TestTheRunRecordsIt:
    """R11.22 row 1, through `execute`: the run's params and its LLM spans."""

    def test_the_run_names_each_steps_model(self, tmp_path: Path):
        """Row 1: params, and each LLM span naming the model that answered it."""
        from dossier.infrastructure.cache import ArtifactCache

        tracker = FakeTracker()
        declared = OutputSchema(schema={"type": "object"}, declaration_hash="d24c86e1" * 8)
        execute(
            workspace=tmp_path,
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
                        model=EXTRACT_MODEL,
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
            model=FakeModelClient(responses=[_abstains("INC-4821")], model_id=PIPELINE_MODEL),
            models={
                EXTRACT_MODEL: FakeModelClient(
                    responses=[_abstains("INC-4821")], model_id=EXTRACT_MODEL
                )
            },
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260806T142203Z-4f1a",
            started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
            dossier_version="0.1.0",
            tracker=tracker,
            experiment="dossier-audit/incident-audit/run",
        )

        (run,) = tracker.runs
        assert run.params["model"] == PIPELINE_MODEL
        assert run.params["model/extract"] == EXTRACT_MODEL
        assert "model/verify" not in run.params
        answered = {
            trace.tags["dossier.step"]: [
                span["dossier.model"] for span in trace.spans if span["kind"] == "llm"
            ]
            for trace in tracker.traces
        }
        assert answered == {"extract": [EXTRACT_MODEL], "verify": [PIPELINE_MODEL]}


class TestTheEvalRecordsIt:
    """R11.22 row 4, through `start_eval`: read off the manifest it reproduced."""

    def test_an_eval_names_each_steps_model(self):
        """Row 4: the eval's params carry `model/extract` from the run's plan (R11.11)."""
        tracker = FakeTracker()

        start_eval(
            tracker,
            experiment="dossier-audit/incident-audit/eval",
            pipeline="incident-audit",
            run_id="20260806T142203Z-4f1a",
            model=PIPELINE_MODEL,
            gold="gold/incidents",
            gold_files={},
            plan=_plan(),
        )

        (run,) = tracker.runs
        assert run.params["model/extract"] == EXTRACT_MODEL
        assert "model/verify" not in run.params
