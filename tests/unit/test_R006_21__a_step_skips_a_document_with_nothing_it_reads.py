"""R6.21 — a step does not run for a document that holds nothing of any kind it reads.

A source mixing pages and pictures converts a PNG to `page_images` and never to
`markdown` (R8.10). Before this rule, a step reading `documents` was asked about
each picture with an empty document. Every picture then had the one key whose
input hash is the hash of `""`, and each picture after the first was served the
first one's answer, naming the first (R6.13's reasoning, found live by playground
exercise 15).

The run is given what `dossier run` gives it for such a source: text for the note,
and parts for each picture. The model client is scripted with exactly the calls
the run may make, so a call for a picture asks for a reply that is not there.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.manifest import Manifest
from dossier.application.run import RunInputs, RunReport, execute, replay
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart
from dossier.infrastructure.cache import ArtifactCache

RUN_ID = "20260806T142203Z-4f1a"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)

NOTE = "81920114"
MATRIX = "81920114/escalation-matrix.png"
ROTA = "81920114/rota.png"
TEXT = {NOTE: STAGE_INPUTS["INC-4821"]}


def parts(*pictures: str) -> dict:
    """Each picture as one page, as `png-pages` makes it (R8.12)."""
    return {
        "page_images": {
            key: [("page-001.png", ImagePart(media_type=PART_TYPE, data=key.encode()))]
            for key in pictures
        }
    }


def answer(document: str) -> str:
    quoted = {
        "field": "loss_amount",
        "value": 48200.00,
        "currency": "CHF",
        "source": {"document": document, "span": LOSS_SPAN},
    }
    return json.dumps({"document": document, "fields": [quoted]})


def run(
    workspace: Path, model: FakeModelClient, *, step: StepConfig, pictures: tuple[str, ...]
) -> RunReport:
    config = PipelineConfig(
        name="procedures-audit", sources=["procedures-confluence"], model=MODEL, steps=[step]
    )
    return execute(
        RunInputs(
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            schemas={step.id: SCHEMA if step.mode != "aggregate" else None},
            prompts={step.id: prompt_for(step.inputs)},
            documents={key: f"{n:08x}" * 8 for n, key in enumerate((NOTE, *pictures), 1)},
            document_text=TEXT,
            document_content={"markdown": TEXT},
            document_parts=parts(*pictures),
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=RUN_ID,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )


EXTRACT = StepConfig(
    id="extract", prompt="prompts/01_extract.md", input="documents", mode="per_file"
)


def records(workspace: Path) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((workspace / ".dossier" / "cache" / "stage").rglob("*.meta.json"))
    ]


class TestAStepSkipsADocumentWithNothingItReads:
    """R6.21 — no text, no call, for a step that reads text."""

    def test_a_picture_is_not_asked_about_by_a_step_reading_text(self, tmp_path: Path):
        """Example 1: the one where the page carries one picture."""
        model = FakeModelClient(responses=[answer(NOTE)])

        report = run(tmp_path, model, step=EXTRACT, pictures=(MATRIX,))

        assert model.call_count == 1
        assert [result.document for result in report.steps[0].results] == [NOTE]
        assert len(records(tmp_path)) == 1

    def test_two_pictures_are_not_served_each_others_answer(self, tmp_path: Path):
        """Example 2: the one where two pictures once shared the key of `""`."""
        model = FakeModelClient(responses=[answer(NOTE)])

        report = run(tmp_path, model, step=EXTRACT, pictures=(MATRIX, ROTA))

        assert model.call_count == 1
        written = [result.document for result in report.steps[0].results]
        assert MATRIX not in written and ROTA not in written

    def test_a_per_part_step_runs_for_the_pictures_and_not_the_note(self, tmp_path: Path):
        """Counter-example, row 3: the one where the step reads pages as pictures."""
        describe = StepConfig(
            id="describe",
            prompt="prompts/01_describe.md",
            input="documents@page_images",
            mode="per_part",
        )
        model = FakeModelClient(responses=[answer(MATRIX), answer(ROTA)])

        report = run(tmp_path, model, step=describe, pictures=(MATRIX, ROTA))

        assert model.call_count == 2
        assert [result.document for result in report.steps[0].results] == [MATRIX, ROTA]

    def test_an_aggregate_step_joins_the_note_and_leaves_the_pictures_out(self, tmp_path: Path):
        """Counter-example, row 4: the one where the step reads a set."""
        summarise = StepConfig(
            id="summarise",
            prompt="prompts/03_summarise.md",
            input="documents",
            mode="aggregate",
        )
        model = FakeModelClient(responses=["One procedure reviewed."])

        run(tmp_path, model, step=summarise, pictures=(MATRIX, ROTA))

        assert model.call_count == 1
        (record,) = records(tmp_path)
        assert record["step"] == "summarise"

    def test_a_skipped_picture_is_not_a_failure(self, tmp_path: Path):
        """Row 5: the one where nothing about the picture went wrong."""
        report = run(
            tmp_path,
            FakeModelClient(responses=[answer(NOTE)]),
            step=EXTRACT,
            pictures=(MATRIX,),
        )

        assert report.failed == []

    def test_a_replay_skips_what_the_run_skipped(self, tmp_path: Path):
        """Row 6: the one where no entry is asked for that the run never wrote (R4.7)."""
        run(
            tmp_path,
            FakeModelClient(responses=[answer(NOTE)]),
            step=EXTRACT,
            pictures=(MATRIX,),
        )
        manifest = Manifest.read(tmp_path / "runs" / RUN_ID / "manifest.json")

        replayed = replay(
            manifest=manifest,
            document_text=TEXT,
            cache=ArtifactCache(tmp_path, namespace="stage"),
            document_parts=parts(MATRIX),
        )

        assert [result.document for result in replayed.steps[0].results] == [NOTE]
