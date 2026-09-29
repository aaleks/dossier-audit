"""R15.6 — a `per_part` document's trace shows each page's answer under the
page's name.

R15.1's response is the answer as `runs/` holds it, and for a `per_part` step
that is one file per page. The run parsed the document's joined `<part>` text
as JSON instead, so with MLflow on every `per_part` run stopped after its first
document -- found live on 2026-09-29, with exercise 10 and a real model.

The decision is the domain's (`trace_pages`); then the run, through `execute`
and a `FakeTracker`, which keeps what each trace was closed with. The documents
are `_fixtures.md`'s "`INC-4830` page by page" and `INC-5720`'s one page.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.fakes import FakeModelClient, FakeTracker
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import RunInputs, RunRecording, execute
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.hashing import content_hash
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart
from dossier.domain.tracking import trace_pages

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUN_ID = "20260929T062520Z-989e"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
CHART = "INC-5720-checkout-latency-postmortem.png"
TEXT = {POSTMORTEM: "SEV-1 | Checkout TLS expiry\nResolved 2026-07-28 07:04 CEST"}
PAGES = {
    POSTMORTEM: [
        (f"page-00{n}.png", ImagePart(media_type=PART_TYPE, data=f"INC-4830 page {n}".encode()))
        for n in (1, 2, 3)
    ],
    CHART: [("page-001.png", ImagePart(media_type=PART_TYPE, data=b"INC-5720 page 1"))],
}
NONSENSE = "no JSON here"
PAGE_1 = '{\n  "document": "INC-4830-postmortem-checkout-tls-expiry.pdf",\n  "fields": []\n}\n'


def _severity(document: str, value: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "severity",
                    "value": value,
                    "source": {"document": document, "span": "SEV-1"},
                }
            ],
        }
    )


# One reply per call, in the order the run asks: INC-4830's three pages, then
# INC-5720's one.
EVERY_PAGE = [
    _severity(POSTMORTEM, "critical"),
    _severity(POSTMORTEM, "critical"),
    _severity(POSTMORTEM, "critical"),
    _severity(CHART, "major"),
]


def _run(
    workspace: Path,
    responses: list[str],
    *,
    capture: str = "full",
    mode: str = "per_part",
) -> FakeTracker:
    """One `extract` step over the postmortem and the chart, recorded."""
    from dossier.infrastructure.cache import ArtifactCache

    source = "documents@page_images" if mode == "per_part" else "documents"
    documents = {POSTMORTEM: TEXT[POSTMORTEM], CHART: ""} if mode == "per_part" else ISSUES
    tracker = FakeTracker()
    execute(
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
                        mode=mode,
                        output="schemas/incident.yaml",
                    )
                ],
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={"extract": SCHEMA},
            prompts={"extract": prompt_for([source])},
            documents={
                key: sha256(text.encode()).hexdigest() for key, text in documents.items()
            },
            document_text=documents,
            document_content={"markdown": documents},
            document_parts={"page_images": PAGES} if mode == "per_part" else None,
        ),
        workspace=workspace,
        model=FakeModelClient(responses=responses),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=RUN_ID,
        started_at=datetime(2026, 9, 29, 6, 25, 20, tzinfo=UTC),
        dossier_version="0.1.0",
        recording=RunRecording(
            tracker=tracker, experiment="dossier-audit/incident-audit/run", capture=capture
        ),
    )
    return tracker


def _trace(tracker: FakeTracker, document: str):
    (trace,) = [trace for trace in tracker.traces if trace.name == f"extract · {document}"]
    return trace


def _written(workspace: Path, document: str, page: str) -> bytes:
    return (workspace / "runs" / RUN_ID / "extract" / document / page).read_bytes()


class TestWhatAPageByPageTraceShows:
    """R15.6 — each page's answer under its name, decided once for every capture."""

    def test_each_page_is_shown_as_json_under_its_name(self):
        """Row 1: the field record each page's file holds, parsed."""
        shown = trace_pages([("page-001.png", PAGE_1)], structured=True, capture="full")

        assert shown == {"page-001.png": json.loads(PAGE_1)}

    def test_under_hashes_each_page_is_its_artifacts_hash(self):
        """Row 4: no text of any answer (R10.8)."""
        shown = trace_pages([("page-001.png", PAGE_1)], structured=True, capture="hashes")

        assert shown == {"page-001.png": {"artifact": content_hash(PAGE_1.encode("utf-8"))}}


class TestARunShowsEachPage:
    """R15.6 — through `execute`: a `per_part` document's trace closed with its pages."""

    def test_a_document_read_page_by_page_shows_every_page(self, tmp_path: Path):
        """Row 1: `extract · INC-4830`, three pages, and the run completes."""
        tracker = _run(tmp_path, list(EVERY_PAGE))

        trace = _trace(tracker, POSTMORTEM)
        assert trace.outputs == {
            page: json.loads(_written(tmp_path, POSTMORTEM, f"{page[:-4]}.json"))
            for page in ("page-001.png", "page-002.png", "page-003.png")
        }

    def test_a_document_of_one_page_is_still_keyed_by_it(self, tmp_path: Path):
        """Row 2: `INC-5720`, whose one page is all `runs/` holds of it."""
        tracker = _run(tmp_path, list(EVERY_PAGE))

        trace = _trace(tracker, CHART)
        assert trace.outputs == {
            "page-001.png": json.loads(_written(tmp_path, CHART, "page-001.json"))
        }

    def test_a_document_with_a_failed_page_shows_its_error(self, tmp_path: Path):
        """Row 3: `INC-4830`'s page 2 not JSON twice (R6.2)."""
        tracker = _run(
            tmp_path,
            [EVERY_PAGE[0], NONSENSE, NONSENSE, EVERY_PAGE[2], EVERY_PAGE[3]],
        )

        trace = _trace(tracker, POSTMORTEM)
        assert trace.status == "ERROR"
        assert trace.outputs == {"error": trace.error}

    def test_under_hashes_no_page_holds_a_word(self, tmp_path: Path):
        """Row 4: each page's file, hashed; `DOSSIER_MLFLOW_CAPTURE=hashes`."""
        tracker = _run(tmp_path, list(EVERY_PAGE), capture="hashes")

        trace = _trace(tracker, POSTMORTEM)
        hashed = {
            page: content_hash(_written(tmp_path, POSTMORTEM, f"{page[:-4]}.json"))
            for page in ("page-001.png", "page-002.png", "page-003.png")
        }
        assert trace.outputs == {page: {"artifact": sha} for page, sha in hashed.items()}
        assert "critical" not in json.dumps(trace.outputs)

    def test_a_document_read_whole_is_keyed_by_no_page(self, tmp_path: Path):
        """Row 5, a counter-example: a `per_file` step shows its record (R15.1 row 1)."""
        answers = [json.dumps({"document": key, "fields": []}) for key in sorted(ISSUES)]
        tracker = _run(tmp_path, answers, mode="per_file")

        trace = _trace(tracker, "INC-4821")
        written = tmp_path / "runs" / RUN_ID / "extract" / "INC-4821.json"
        assert trace.outputs == json.loads(written.read_text(encoding="utf-8"))
