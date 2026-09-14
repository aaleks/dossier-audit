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
from tests.pipelines import DECLARATION, PROVIDERS, prompt_for, write_pipeline

from dossier.application.run import execute
from dossier.domain.keys import ConvertInputs
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


PROSE = "INC-4821: a loss of CHF 48'200. The root cause is not stated.\n"


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


def run(
    workspace: Path,
    model,
    *,
    declaration: str,
    run_id: str,
    config: PipelineConfig | None = None,
):
    """One run, every declaring step's schema loaded from `declaration` as the CLI loads it."""
    from dossier.config.load import load_output_schema

    path = workspace / "pipelines" / "incident-audit" / OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(declaration, encoding="utf-8")

    config = config or pipeline()
    output = load_output_schema(path)
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


class TestFieldDeclarationHashIsPartOfAffectedKeys:
    """R6.11 — the declaration, hashed as text, fills the stage key's schema slot."""

    def test_editing_the_declaration_reruns_the_steps_that_declare_it(self, tmp_path: Path):
        """Example 1: the one where `extract` and `verify` move, and `report` does not.

        Both declare `schemas/incident.yaml`, so both keys carry its hash.
        `report` declares nothing: its key moves only when what it reads moves,
        so an edit that leaves `verify`'s answer unchanged leaves `report` cached.
        """
        run(
            tmp_path,
            FakeModelClient(responses=[answer("INC-4821"), answer("INC-4821"), PROSE]),
            declaration=DECLARATION,
            run_id="20260806T142203Z-4f1a",
            config=chain(),
        )

        edited = "".join(
            line
            for line in DECLARATION.splitlines(keepends=True)
            if "affected_systems" not in line
        )
        model = FakeModelClient(responses=[answer("INC-4821"), answer("INC-4821")])
        report = run(
            tmp_path, model, declaration=edited, run_id="20260907T090000Z-bbbb", config=chain()
        )

        extract, verify, summary = report.steps
        assert model.call_count == 2, "`extract` and `verify` asked again, `report` not"
        assert extract.served_from_cache == ()
        assert verify.served_from_cache == ()
        assert len(summary.served_from_cache) == 1

    def test_a_declaration_no_step_names_is_in_no_key(self, tmp_path: Path):
        """Counter-example (row 4): the one where `schemas/contract.yaml` sits unused.

        Only the declarations a step's `output` names are loaded, so a file
        beside them -- a draft, another use case's fields -- moves nothing until
        a step names it. `report`, which names none, gets none (R3.10 row 5).
        """
        from dossier.config.load import load_output_schemas, load_pipeline

        path = write_pipeline(
            tmp_path,
            steps=["extract", "report"],
            inputs={"report": "extract"},
            outputs={"report": None},
        )
        contract = path.parent / "schemas" / "contract.yaml"
        contract.write_text(DECLARATION, encoding="utf-8")
        config = load_pipeline(path, providers=PROVIDERS)
        before = load_output_schemas(config, path)

        contract.write_text(
            DECLARATION.replace("rubrics/root_cause.md", "rubrics/contract.md"),
            encoding="utf-8",
        )
        after = load_output_schemas(config, path)

        assert set(after) == {"extract"}
        assert after == before

    def test_a_declaration_has_nowhere_to_go_in_a_convert_key(self):
        """Example 2: the one where editing `incident.yaml` re-converts nothing.

        Converting a document does not depend on what will be extracted from it
        (R5.4). The strongest form of that is structural: not that a convert key
        leaves the declaration out, but that it has no slot one could fill.
        """
        conversion = ConvertInputs(
            snapshot="a3f9c1e2" * 8, converter_id="pdf-markdown", converter_version="1.3.0"
        )

        assert "schema" not in conversion.keyed()
        assert set(conversion.keyed()) == {
            "snapshot",
            "converter_id",
            "converter_version",
            "options",
        }

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
