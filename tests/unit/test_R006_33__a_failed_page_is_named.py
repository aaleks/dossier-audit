"""R6.33 — a page-by-page document's reason names each page that failed.

A `per_part` document fails when a page does (R3.12). Its reason joined its
pages' reasons without saying which page gave them, so one failure among four
pages read as the document's. Each page's reason now starts with its name, as a
miss does when `dossier eval` names the page (R7.48), in page order.

Through `execute`, with `_fixtures.md`'s "`INC-4830` page by page" as three
pictures, and a `FakeModelClient` answering in the order the pages are asked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, RunReport, execute
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
INCIDENT = "INC-4822"
NOT_JSON = "not JSON at all"
INVALID = "no valid output after 2 attempts: Invalid JSON: expected ident at line 1 column 2"
PAGES = [
    (f"page-00{n}.png", ImagePart(media_type=PART_TYPE, data=f"INC-4830 page {n}".encode()))
    for n in (1, 2, 3)
]


def _answer(document: str) -> str:
    return json.dumps({"document": document, "fields": []})


def _execute(workspace: Path, replies: list[str], *, paged: bool = True) -> RunReport:
    """`extract` over the postmortem page by page, or over `INC-4822` whole."""
    from dossier.infrastructure.cache import ArtifactCache

    document = POSTMORTEM if paged else INCIDENT
    source = "documents@page_images" if paged else "documents"
    text = {document: "SEV-1 | Checkout TLS expiry" if paged else "# INC-4822\n\nTimed out.\n"}
    return execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit",
                sources=["postmortems"],
                model=MODEL,
                steps=[
                    StepConfig(
                        id="extract",
                        prompt="prompts/extract.md",
                        input=source,
                        mode="per_part" if paged else "per_file",
                        output="schemas/incident.yaml",
                    )
                ],
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={"extract": SCHEMA},
            prompts={"extract": prompt_for([source])},
            documents={document: sha256(document.encode()).hexdigest()},
            document_text=text,
            document_content={"markdown": text},
            document_parts={"page_images": {POSTMORTEM: PAGES}} if paged else None,
        ),
        workspace=workspace,
        model=FakeModelClient(responses=replies),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260929T160000Z-0c0c",
        started_at=datetime(2026, 9, 29, 16, 0, tzinfo=UTC),
        dossier_version="0.1.0",
    )


def _error(report: RunReport) -> str | None:
    (step,) = report.steps
    (result,) = step.results
    return result.error


class TestAFailedPageIsNamed:
    """R6.33 — each failed page's reason starts with its name, in page order."""

    def test_the_page_that_failed_is_named(self, tmp_path: Path):
        """Row 1 — the one where page 2 of three answered prose twice."""
        page = _answer(POSTMORTEM)

        report = _execute(tmp_path, [page, NOT_JSON, NOT_JSON, page])

        assert _error(report) == f"page-002.png: {INVALID}"

    def test_two_failed_pages_are_named_in_page_order(self, tmp_path: Path):
        """Row 2 — the one where pages 2 and 3 both answered prose twice."""
        page = _answer(POSTMORTEM)

        report = _execute(tmp_path, [page, NOT_JSON, NOT_JSON, NOT_JSON, NOT_JSON])

        assert _error(report) == f"page-002.png: {INVALID}; page-003.png: {INVALID}"

    def test_a_document_read_whole_names_no_page(self, tmp_path: Path):
        """Row 3, counter-example — the one with no page to name."""
        report = _execute(tmp_path, [NOT_JSON, NOT_JSON], paged=False)

        assert _error(report) == INVALID
