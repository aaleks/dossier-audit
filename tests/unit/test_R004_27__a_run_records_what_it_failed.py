"""R4.27 — a run records each unit it failed, with the step and the reason, in
`runs/<run_id>/failures.json`.

A failed document leaves no artifact (R0.11 row 4), and nothing recorded that
it failed, so a replay could not tell a failure from a lost cache entry, and
stopped (R4.7 row 4). The record is one file beside the manifest, written when
the run ends: one entry per failed unit, a document or a page. A skip is not a
failure, and a run that failed nothing writes `[]`.

Through `execute`, with `FakeModelClient`s answering in the order they are asked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, execute
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
RUN_ID = "20260929T170000Z-0d0d"
NOT_JSON = "not JSON at all"
REASON = "no valid output after 2 attempts: Invalid JSON: expected ident at line 1 column 2"
TEXT = {
    "INC-4821": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PAGES = [
    (f"page-00{n}.png", ImagePart(media_type=PART_TYPE, data=f"INC-4830 page {n}".encode()))
    for n in (1, 2, 3)
]


def _answer(document: str) -> str:
    return json.dumps({"document": document, "fields": []})


def _step(step: str, source: str, *, mode: str = "per_file", structured: bool = True):
    return StepConfig(
        id=step,
        prompt=f"prompts/{step}.md",
        input=source,
        mode=mode,
        output="schemas/incident.yaml" if structured else None,
    )


def _execute(
    workspace: Path,
    replies: list[str],
    *,
    steps: list[StepConfig] | None = None,
    text: dict[str, str] = TEXT,
    parts: dict | None = None,
) -> None:
    from dossier.infrastructure.cache import ArtifactCache

    steps = steps or [_step("extract", "documents")]
    execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit", sources=["incidents-jira"], model=MODEL, steps=steps
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={step.id: SCHEMA if step.output else None for step in steps},
            prompts={step.id: prompt_for([step.input]) for step in steps},
            documents={key: sha256(key.encode()).hexdigest() for key in text},
            document_text=text,
            document_content={"markdown": text},
            document_parts=parts,
        ),
        workspace=workspace,
        model=FakeModelClient(responses=replies),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=RUN_ID,
        started_at=datetime(2026, 9, 29, 17, 0, tzinfo=UTC),
        dossier_version="0.1.0",
    )


def _recorded(workspace: Path) -> list[dict]:
    return json.loads((workspace / "runs" / RUN_ID / "failures.json").read_text("utf-8"))


class TestARunRecordsWhatItFailed:
    """R4.27 — one entry per failed unit, beside the manifest, when the run ends."""

    def test_a_document_that_failed_is_recorded(self, tmp_path: Path):
        """Row 1 — the one where INC-4822 answered prose on both attempts."""
        _execute(tmp_path, [_answer("INC-4821"), NOT_JSON, NOT_JSON])

        assert _recorded(tmp_path) == [
            {"step": "extract", "document": "INC-4822", "part": None, "reason": REASON}
        ]

    def test_a_page_that_failed_is_recorded_as_the_page(self, tmp_path: Path):
        """Row 2 — the one where page 2 of three failed, its reason its own."""
        page = _answer(POSTMORTEM)

        _execute(
            tmp_path,
            [page, NOT_JSON, NOT_JSON, page],
            steps=[_step("extract", "documents@page_images", mode="per_part")],
            text={POSTMORTEM: "SEV-1 | Checkout TLS expiry"},
            parts={"page_images": {POSTMORTEM: PAGES}},
        )

        page_two = {"part": "page-002.png", "reason": REASON}
        assert _recorded(tmp_path) == [{"step": "extract", "document": POSTMORTEM, **page_two}]

    def test_a_skip_is_not_a_failure(self, tmp_path: Path):
        """Row 3 — the one where `verify` skips INC-4822, which `extract` failed (R6.13)."""
        steps = [_step("extract", "documents"), _step("verify", "extract")]

        _execute(
            tmp_path,
            [_answer("INC-4821"), NOT_JSON, NOT_JSON, _answer("INC-4821")],
            steps=steps,
        )

        assert _recorded(tmp_path) == [
            {"step": "extract", "document": "INC-4822", "part": None, "reason": REASON}
        ]

    def test_a_run_that_failed_nothing_records_an_empty_list(self, tmp_path: Path):
        """Row 4, counter-example — the one that finished clean."""
        _execute(tmp_path, [_answer("INC-4821"), _answer("INC-4822")])

        assert _recorded(tmp_path) == []

    def test_a_run_that_stopped_records_nothing(self, tmp_path: Path):
        """Row 5, counter-example — the one stopped before it ended (R11.23)."""
        # The model is scripted for one call and asked for two: the second stops
        # the run, as an unreachable model does.
        with pytest.raises(Exception, match="no scripted response left"):
            _execute(tmp_path, [_answer("INC-4821")])

        assert (tmp_path / "runs" / RUN_ID / "manifest.json").is_file()
        assert not (tmp_path / "runs" / RUN_ID / "failures.json").exists()
