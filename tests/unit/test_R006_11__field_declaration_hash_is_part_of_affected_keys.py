"""R6.11 — a step's field declaration is part of every key that step's output depends on.

R6.8 hashed a hand-written JSON Schema. Under R6.10 the JSON Schema is generated
from a YAML declaration, and the declaration is what the key hashes -- as text,
the way spec 005 hashes every configuration file. The generated schema carries
only field names, so a key taken over it would miss every edit it cannot see.

The cache claims are measured through a real run, as R5.2's are: "the key is
different" and "the model was actually asked again" are different statements,
and the rule is about the second.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import DECLARATION, prompt_for

from dossier.application.run import execute
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8}
TEXT = {"INC-4821": STAGE_INPUTS["INC-4821"]}
OUTPUT = "schemas/incident.yaml"


def answer(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "loss_amount",
                    "value": 48200.00,
                    "currency": "CHF",
                    "source": {"document": document, "span": LOSS_SPAN},
                }
            ],
        }
    )


def pipeline() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/01_extract.md",
                input="documents",
                mode="per_file",
                output=OUTPUT,
            ),
        ],
    )


def run(workspace: Path, model, *, declaration: str, run_id: str):
    """One run of `extract`, its schema loaded from `declaration` the way the CLI loads it."""
    from dossier.config.load import load_output_schema

    path = workspace / "pipelines" / "incident-audit" / OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(declaration, encoding="utf-8")

    config = pipeline()
    return execute(
        workspace=workspace,
        pipeline=config,
        pipeline_hash=PIPELINE_HASH,
        documents=DOCUMENTS,
        document_text=TEXT,
        schemas={"extract": load_output_schema(path)},
        prompts={step.id: prompt_for(step.inputs) for step in config.steps},
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


class TestFieldDeclarationHashIsPartOfAffectedKeys:
    """R6.11 — the declaration, hashed as text, fills the stage key's schema slot."""

    def test_an_edit_the_generated_schema_cannot_see_still_moves_the_key(self, tmp_path: Path):
        """Example 3: the one where only the rubric `root_cause` is judged by changes.

        The generated schema names fields and nothing else, so it is identical
        before and after this edit. A key taken over it would serve the old
        answer; a key over the declaration's text asks again.
        """
        run(
            tmp_path,
            FakeModelClient(responses=[answer("INC-4821")]),
            declaration=DECLARATION,
            run_id="20260806T142203Z-4f1a",
        )

        edited = DECLARATION.replace("rubrics/root_cause.md", "rubrics/root_cause_v2.md")
        model = FakeModelClient(responses=[answer("INC-4821")])
        report = run(tmp_path, model, declaration=edited, run_id="20260907T090000Z-bbbb")

        assert model.call_count == 1
        assert report.steps[0].served_from_cache == ()
