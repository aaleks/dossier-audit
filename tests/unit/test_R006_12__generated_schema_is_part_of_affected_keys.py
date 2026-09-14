"""R6.12 — the schema the model is shown is part of every key its step's output depends on.

R6.11 keys the declaration's text. The JSON Schema shown to the model is
generated from that declaration by dossier's own code, so a change to the code --
a property added to the record model, a library that renders the schema
differently -- changes what the model is asked with no byte of the declaration
moving. R6.12 puts the generated schema's hash beside the declaration's, so that
change moves a key too (R0.5).

The cache claims are measured through a real run, as R5.2's and R6.11's are.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import DECLARATION, prompt_for

from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8}
TEXT = {"INC-4821": STAGE_INPUTS["INC-4821"]}
OUTPUT = "schemas/incident.yaml"

# `incident.yaml`, unchanged throughout: the declaration's hash never moves here.
DECLARATION_HASH = "6e0d4b27" * 8

# What the model is shown, before and after the record model gains a property.
SHOWN = {"type": "object", "properties": {"field": {"enum": ["loss_amount"]}}}
GROWN = {
    "type": "object",
    "properties": {"field": {"enum": ["loss_amount"]}, "note": {"type": "string"}},
}

PROSE = "INC-4821: a loss of CHF 48'200. The root cause is not stated.\n"


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


def chain() -> PipelineConfig:
    """`extract` -> `verify` -> `report`. The first two declare fields; `report` is prose."""
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
            StepConfig(
                id="verify",
                prompt="prompts/02_verify.md",
                input="extract",
                mode="per_file",
                output=OUTPUT,
            ),
            StepConfig(
                id="report", prompt="prompts/03_report.md", input="verify", mode="per_file"
            ),
        ],
    )


def run(workspace: Path, model, *, shown: dict, run_id: str):
    """One run over `chain()`, every declaring step shown `shown` under one declaration."""
    config = chain()
    output = OutputSchema(schema=shown, declaration_hash=DECLARATION_HASH)
    return execute(
        workspace=workspace,
        pipeline=config,
        pipeline_hash=PIPELINE_HASH,
        documents=DOCUMENTS,
        document_text=TEXT,
        schemas={step.id: output for step in config.steps if step.output is not None},
        prompts={step.id: prompt_for(step.inputs) for step in config.steps},
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


class TestGeneratedSchemaIsPartOfAffectedKeys:
    """R6.12 — what the model is shown moves the key, even when the declaration does not."""

    def test_a_grown_record_model_reruns_the_steps_that_declare_fields(self, tmp_path: Path):
        """Example 1: the one where the record model grows and `incident.yaml` does not.

        The declaration's hash is `6e0d4b27` in both runs, so R6.11 alone would
        serve the old answer. `report` declares nothing and its input does not
        change, so it is still served from cache.
        """
        run(
            tmp_path,
            FakeModelClient(responses=[answer("INC-4821"), answer("INC-4821"), PROSE]),
            shown=SHOWN,
            run_id="20260806T142203Z-4f1a",
        )

        model = FakeModelClient(responses=[answer("INC-4821"), answer("INC-4821")])
        report = run(tmp_path, model, shown=GROWN, run_id="20260907T090000Z-bbbb")

        extract, verify, summary = report.steps
        assert model.call_count == 2, "`extract` and `verify` asked again, `report` not"
        assert extract.served_from_cache == ()
        assert verify.served_from_cache == ()
        assert len(summary.served_from_cache) == 1

    def test_the_same_schema_built_in_another_order_hashes_the_same(self):
        """Example 2: the one where the dict was built the other way round.

        Hashed as canonical JSON, not as a dict happened to be assembled: two
        machines building the same schema in a different order share a key (R5.6).
        """
        forwards = OutputSchema(
            schema={"type": "object", "properties": {"field": {"enum": ["loss_amount"]}}},
            declaration_hash=DECLARATION_HASH,
        )
        backwards = OutputSchema(
            schema={"properties": {"field": {"enum": ["loss_amount"]}}, "type": "object"},
            declaration_hash=DECLARATION_HASH,
        )

        assert forwards.generated_schema_hash == backwards.generated_schema_hash

    def test_a_rubric_edit_moves_the_declaration_hash_and_not_the_generated_one(
        self, tmp_path: Path
    ):
        """Example 3: the one where only the rubric `root_cause` names as its `judge` changes.

        The key still moves, through the declaration (R6.11 row 3). The generated
        schema names fields and nothing else, so its hash stays put: the two slots
        answer different questions, and neither stands in for the other.
        """
        from dossier.config.load import load_output_schema

        before_path = tmp_path / "before.yaml"
        before_path.write_text(DECLARATION, encoding="utf-8")
        after_path = tmp_path / "after.yaml"
        after_path.write_text(
            DECLARATION.replace("rubrics/root_cause.md", "rubrics/root_cause_v2.md"),
            encoding="utf-8",
        )

        before = load_output_schema(before_path)
        after = load_output_schema(after_path)

        assert before.declaration_hash != after.declaration_hash
        assert before.generated_schema_hash == after.generated_schema_hash

    def test_a_step_with_no_output_has_nothing_in_either_schema_slot(self, tmp_path: Path):
        """Counter-example (row 4): the one where `report` writes prose.

        No declaration, so no generated schema: both slots of its key are empty,
        and it moves only through its inputs (R6.11 row 1). `extract`, beside it,
        carries the hash of exactly what it was shown.
        """
        report = run(
            tmp_path,
            FakeModelClient(responses=[answer("INC-4821"), answer("INC-4821"), PROSE]),
            shown=SHOWN,
            run_id="20260806T142203Z-4f1a",
        )

        manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
        steps = {step["id"]: step for step in manifest["plan"]["steps"]}
        shown = OutputSchema(schema=SHOWN, declaration_hash=DECLARATION_HASH)

        assert steps["report"]["schema_hash"] is None
        assert steps["report"]["generated_schema_hash"] is None
        assert steps["extract"]["generated_schema_hash"] == shown.generated_schema_hash
