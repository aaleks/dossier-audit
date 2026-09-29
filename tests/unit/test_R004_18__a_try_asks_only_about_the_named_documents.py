"""R4.18 — `dossier run --doc KEY` asks every step only about the named documents.

A try is asked what a full run would ask about the named documents, and
nothing about any other. Run through `execute`, whose `tried` is what `--doc`
names, with a `FakeModelClient` that **counts calls** and keeps each prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for
from tests.scoring_example import FIFTH_ISSUE, ISSUES

from dossier.application.run import RunInputs, execute
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart

TEXT = {**ISSUES, **FIFTH_ISSUE}
DOCUMENTS = tuple(sorted(TEXT))
# `_fixtures.md`'s contracts: ACME-2024 is a master and two amendments, and
# GLOBEX-2023 a group of one.
CONTRACTS = {
    "ACME-2024/amendment-1.pdf": "Amendment 1 changes the invoicing address.",
    "ACME-2024/amendment-3.pdf": "Amendment 3 extends the term to 2027-03-31.",
    "ACME-2024/master.pdf": "Liability is capped at EUR 2,000,000.",
    "GLOBEX-2023/master.pdf": "The term ends 2026-12-31.",
}
# `_fixtures.md`'s "`INC-4830` page by page", beside `INC-5720`'s one page.
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
CHART = "INC-5720-checkout-latency-postmortem.png"
PICTURES = {POSTMORTEM: "SEV-1 | Checkout TLS expiry", CHART: ""}
PAGES = {
    POSTMORTEM: [
        (f"page-00{n}.png", ImagePart(media_type=PART_TYPE, data=f"INC-4830 page {n}".encode()))
        for n in (1, 2, 3)
    ],
    CHART: [("page-001.png", ImagePart(media_type=PART_TYPE, data=b"INC-5720 page 1"))],
}


def _snapshot(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _run(
    workspace: Path,
    *,
    tried: tuple[str, ...] | None,
    mode: str = "per_file",
    text: dict[str, str] = TEXT,
) -> FakeModelClient:
    """`extract` over `text`, in `mode`; the model, having been asked.

    A `per_part` step reads each document's pages, and is answered once a page.
    """
    from dossier.infrastructure.cache import ArtifactCache

    paged = mode == "per_part"
    source = "documents@page_images" if paged else "documents"
    model = FakeModelClient(
        responses=[
            json.dumps({"document": key, "fields": []})
            for key in sorted(text)
            for _ in (PAGES[key] if paged else [None])
        ]
    )
    execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit",
                sources=["incidents-jira"],
                model="anthropic:claude-sonnet-4-5-20250929",
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
            pipeline_hash="6e0d4b27" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt_for([source])},
            documents={key: _snapshot(body) for key, body in text.items()},
            document_text=text,
            document_content={"markdown": text},
            document_parts={"page_images": PAGES} if paged else None,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260929T100000Z-1a2b",
        started_at=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
        dossier_version="0.1.0",
        tried=tried,
    )
    return model


def _about(model: FakeModelClient) -> list[list[str]]:
    """Which of the five documents each call's prompt holds, call by call."""
    return [
        [key for key in DOCUMENTS if TEXT[key] in str(call["prompt"])] for call in model.calls
    ]


def _shown(model: FakeModelClient) -> list[list[str]]:
    """The documents each call was handed, each wrapped under its own key (R3.13)."""
    wrapped = re.compile(r'<document key="([^"]+)">')
    return [wrapped.findall(str(call["prompt"])) for call in model.calls]


class TestATryAsksOnlyAboutTheNamedDocuments:
    """R4.18 — `dossier run --doc KEY` asks every step only about the named documents."""

    def test_one_named_document_is_the_one_asked_about(self, tmp_path: Path):
        """Row 1 — the one where four of five incidents are left alone."""
        model = _run(tmp_path, tried=("INC-4821",))

        assert model.call_count == 1
        assert _about(model) == [["INC-4821"]]

    def test_a_document_read_page_by_page_is_asked_about_every_page(self, tmp_path: Path):
        """Row 2 — the one where the postmortem's three pages are asked, and the chart's not."""
        model = _run(tmp_path, tried=(POSTMORTEM,), mode="per_part", text=PICTURES)

        assert [call["parts"] for call in model.calls] == [
            (part,) for _, part in PAGES[POSTMORTEM]
        ]

    def test_two_named_documents_are_asked_about_once_each(self, tmp_path: Path):
        """Row 3 — the one where `--doc` is given twice."""
        model = _run(tmp_path, tried=("INC-4821", "INC-4822"))

        assert _about(model) == [["INC-4821"], ["INC-4822"]]

    def test_a_named_member_is_asked_about_with_its_whole_group(self, tmp_path: Path):
        """Row 4 — the one where an amendment brings its master and its sibling.

        A `per_group` step's unit is the group (R3.15). Asked about amendment 3
        alone, it would be a different question from the one a full run asks
        (R4.15), and its answer a different key's.
        """
        model = _run(
            tmp_path, tried=("ACME-2024/amendment-3.pdf",), mode="per_group", text=CONTRACTS
        )

        assert _shown(model) == [
            ["ACME-2024/amendment-1.pdf", "ACME-2024/amendment-3.pdf", "ACME-2024/master.pdf"]
        ]

    def test_a_run_naming_no_document_asks_about_every_one(self, tmp_path: Path):
        """Row 5, counter-example — the one with no `--doc`: a run as it always was."""
        model = _run(tmp_path, tried=None)

        assert _about(model) == [[key] for key in DOCUMENTS]
