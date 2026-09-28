"""R6.13 — a step does not run for a document an earlier step produced nothing for.

R6.9 says a failed document does not stop the run. This is what the steps above
it do about that document: nothing. Handing the step an empty input instead asks
a model about a document nobody read, and caches the answer under a key whose
input hash is the hash of `""` (R5.5).

`INC-4822` fails `extract` twice -- the attempt and its retry (R6.2) -- while
`INC-4821` is extracted normally. The model client is scripted with exactly the
calls the run is allowed to make, so a step that runs for `INC-4822` anyway asks
for a reply that is not there and says so by name.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, RunReport, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

RUN_ID = "20260806T142203Z-4f1a"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)

DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8}
TEXT = {
    key: STAGE_INPUTS["INC-4821"].replace("INC-4821", key) + f"\n\nFiled as {key}.\n"
    for key in DOCUMENTS
}

# Not JSON at all, so every attempt fails validation (R6.9).
NONSENSE = "no JSON here"
SUMMARY = "One incident reviewed."


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


def pipeline(second: StepConfig) -> PipelineConfig:
    """`extract` over the documents, then whatever step reads it."""
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/01_extract.md",
                input="documents",
                mode="per_file",
            ),
            second,
        ],
    )


VERIFY = StepConfig(
    id="verify", prompt="prompts/02_verify.md", input="extract", mode="per_file"
)
SUMMARISE = StepConfig(
    id="summarise", prompt="prompts/03_summarise.md", input="extract", mode="aggregate"
)


def run(
    workspace: Path, model: FakeModelClient, *, second: StepConfig, schemas: dict
) -> RunReport:
    config = pipeline(second)
    return execute(
        RunInputs(
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            schemas=schemas,
            prompts={step.id: prompt_for(step.inputs) for step in config.steps},
            documents=DOCUMENTS,
            document_text=TEXT,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=RUN_ID,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


def records(workspace: Path) -> list[dict]:
    """Every provenance record the run wrote, so artifacts can be counted by step."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((workspace / ".dossier" / "cache" / "stage").rglob("*.meta.json"))
    ]


class TestAStepSkipsADocumentWithNoUpstreamOutput:
    """R6.13 — a step does not run for a document an earlier step produced nothing for."""

    def test_the_step_above_a_failure_does_not_run_for_that_document(self, tmp_path: Path):
        """Example 1: the one where `INC-4822` fails `extract` and `verify` reads `extract`.

        No model call, no artifact, no cache entry. The script holds exactly the
        four calls the run may make -- one `extract` each, one retry for the
        failure, one `verify` for the document that has an input.
        """
        model = FakeModelClient(
            responses=[answer("INC-4821"), NONSENSE, NONSENSE, answer("INC-4821")]
        )

        run(tmp_path, model, second=VERIFY, schemas={"extract": SCHEMA, "verify": SCHEMA})

        assert model.call_count == 4
        verified = [record for record in records(tmp_path) if record["step"] == "verify"]
        assert [entry["path"] for entry in verified[0]["inputs"]] == ["extract/INC-4821"]
        assert len(verified) == 1

    def test_the_documents_that_succeeded_are_unaffected(self, tmp_path: Path):
        """Example 2: the one where `INC-4821` is verified as usual.

        One document's failure is not the corpus's (R6.9): the step runs for
        every document that has an input, and only skips the one that has none.
        """
        model = FakeModelClient(
            responses=[answer("INC-4821"), NONSENSE, NONSENSE, answer("INC-4821")]
        )

        report = run(
            tmp_path, model, second=VERIFY, schemas={"extract": SCHEMA, "verify": SCHEMA}
        )

        verify = report.steps[1]
        assert [result.document for result in verify.results] == ["INC-4821"]
        assert verify.results[0].records

    def test_the_document_is_reported_once_under_the_step_that_failed(self, tmp_path: Path):
        """Example 3: the one where the failure list is a list of causes.

        `INC-4822` appears once, under `extract`. A second entry under `verify`
        would report a consequence as though it were another cause.
        """
        model = FakeModelClient(
            responses=[answer("INC-4821"), NONSENSE, NONSENSE, answer("INC-4821")]
        )

        report = run(
            tmp_path, model, second=VERIFY, schemas={"extract": SCHEMA, "verify": SCHEMA}
        )

        assert report.failed == [("extract", "INC-4822")]

    def test_an_aggregate_step_still_runs_over_what_did_produce_output(self, tmp_path: Path):
        """Counter-example (row 4): the one where the second step is `aggregate`.

        It runs, over the documents that produced output. An aggregate reads a
        set, and a member absent from it is not a missing input -- so skipping
        the step entirely would throw away the nine documents that worked.
        """
        model = FakeModelClient(responses=[answer("INC-4821"), NONSENSE, NONSENSE, SUMMARY])

        report = run(
            tmp_path, model, second=SUMMARISE, schemas={"extract": SCHEMA, "summarise": None}
        )

        summarise = report.steps[1]
        assert len(summarise.results) == 1
        assert summarise.results[0].failed is False
        assert report.failed == [("extract", "INC-4822")]
        assert model.call_count == 4
