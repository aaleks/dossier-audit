"""R6.23 — a field cites a document its call was shown: the call's own document,
its group or its corpus, and every reference document when its step reads
`reference`.

R6.3 says a field cites an input of its stage, and `check_field` enforces it
when handed the right documents. The run handed a `per_file` call's check the
whole corpus, so an answer about `INC-4821` quoting `INC-4822` -- a span really
there -- was grounded: a citation of a document the call never read, which looks
checkable. R6.22 closed that for a group; this closes it for every mode, and
admits the reference documents R6.3 row 3 always said were inputs.

Run through `execute`, because which documents a call was shown is a fact about
the run, not about the field. A replay grades an answer as the run did, or
`dossier eval`, which scores a replay, would pass the citation the run refused.
The model is a fake that gives every call the same scripted fields (R0.1).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.pipelines import prompt_for

from dossier.application.manifest import Manifest
from dossier.application.run import RunInputs, execute, replay
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.grounding import FieldVerdict
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart
from dossier.infrastructure.cache import ArtifactCache

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
INCIDENTS = {
    "INC-4821": "Finance confirmed a total exposure CHF 48'200.",
    "INC-4822": "The payment gateway timed out for two hours.",
}
CONTRACTS = {
    "ACME-2024/amendment-3.pdf": "Amendment 3 extends the term to 2027-03-31.",
    "ACME-2024/master.pdf": "Liability is capped at EUR 2,000,000.",
}
PROCEDURES = {"OPS-114": "Escalate within 30 minutes."}
SHOWN = re.compile(r'<document key="([^"]+)">')


def _cited(document: str, span: str) -> dict:
    return {
        "field": "root_cause",
        "value": span,
        "source": {"document": document, "span": span},
    }


OWN = _cited("INC-4821", "total exposure CHF 48'200")
NEIGHBOUR = _cited("INC-4822", "timed out for two hours")
PROCEDURE = _cited("OPS-114", "Escalate within 30 minutes")


class Answers:
    """Gives every call the same fields, about the first document it was shown.

    A call shown only a page carries no key in its text, and answers for
    `INC-4821`, the one document with a page.
    """

    model_id = MODEL

    def __init__(self, *fields: dict) -> None:
        self.fields = list(fields)

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        about = (SHOWN.findall(prompt) or ["INC-4821"])[0]
        return json.dumps({"document": about, "fields": self.fields})


def _run(
    tmp_path: Path,
    answers: Answers,
    *,
    mode: str = "per_file",
    inputs: str | list[str] = "documents",
    documents: dict[str, str] = INCIDENTS,
    parts: dict | None = None,
):
    """One step over `documents`, with `OPS-114` as reference; the run's report."""
    declared = inputs if isinstance(inputs, list) else [inputs]
    return execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit",
                sources=["incidents-jira"],
                reference=["procedures-confluence"],
                model=MODEL,
                steps=[
                    StepConfig(id="verify", prompt="prompts/verify.md", input=inputs, mode=mode)
                ],
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={"verify": SCHEMA},
            prompts={"verify": prompt_for(declared)},
            documents={
                key: sha256(text.encode()).hexdigest() for key, text in documents.items()
            },
            document_text=documents,
            document_content={"markdown": documents},
            document_parts=parts,
            reference_content={"markdown": PROCEDURES},
            reference_documents={
                key: sha256(t.encode()).hexdigest() for key, t in PROCEDURES.items()
            },
        ),
        workspace=tmp_path,
        model=answers,
        cache=ArtifactCache(tmp_path, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )


def _verdicts(report, unit: str) -> list[FieldVerdict]:
    (step,) = report.steps
    (result,) = [result for result in step.results if result.document == unit]
    return [check.verdict for check in result.checks]


class TestAFieldCitesADocumentItsCallWasShown:
    """R6.23 — what a call may cite is what it was shown."""

    def test_citing_the_calls_own_document_is_grounded(self, tmp_path: Path):
        """Row 1: the one where `INC-4821`'s answer quotes `INC-4821`."""
        report = _run(tmp_path, Answers(OWN))

        assert _verdicts(report, "INC-4821") == [FieldVerdict.VALID]

    def test_citing_another_document_of_the_corpus_is_invalid(self, tmp_path: Path):
        """Row 2: the one where `INC-4821`'s answer quotes `INC-4822`.

        The span is really in `INC-4822`, which is what makes it dangerous: a
        reviewer would find the quote. A replay grades it as the run did.
        """
        report = _run(tmp_path, Answers(NEIGHBOUR))
        replayed = replay(
            manifest=Manifest.read(report.manifest_path),
            document_text={**INCIDENTS, **PROCEDURES},
            cache=ArtifactCache(tmp_path, namespace="stage"),
        )

        assert _verdicts(report, "INC-4821") == [FieldVerdict.INVALID]
        assert _verdicts(replayed, "INC-4821") == [FieldVerdict.INVALID]

    def test_citing_a_reference_document_the_step_reads_is_grounded(self, tmp_path: Path):
        """Row 3: the one where `verify` reads the procedures and quotes one."""
        report = _run(tmp_path, Answers(PROCEDURE), inputs=["documents", "reference"])

        assert _verdicts(report, "INC-4821") == [FieldVerdict.VALID]

    def test_citing_a_reference_document_the_step_does_not_read_is_invalid(
        self, tmp_path: Path
    ):
        """Row 4: the one where `extract` quotes a procedure it was never shown."""
        report = _run(tmp_path, Answers(PROCEDURE))

        assert _verdicts(report, "INC-4821") == [FieldVerdict.INVALID]

    def test_a_page_of_one_document_cannot_cite_another(self, tmp_path: Path):
        """Row 5: the one where a `per_part` call on `INC-4821`'s page quotes `INC-4822`."""
        page = ImagePart(media_type=PART_TYPE, data=b"INC-4821 page 1")
        report = _run(
            tmp_path,
            Answers(NEIGHBOUR),
            mode="per_part",
            inputs="documents@page_images",
            parts={"page_images": {"INC-4821": [("page-001.png", page)]}},
        )

        assert _verdicts(report, "INC-4821") == [FieldVerdict.INVALID]

    def test_a_group_reading_reference_may_cite_it(self, tmp_path: Path):
        """Row 6: the one where a contract's answer quotes the procedure it was shown."""
        report = _run(
            tmp_path,
            Answers(PROCEDURE),
            mode="per_group",
            inputs=["documents", "reference"],
            documents=CONTRACTS,
        )

        assert _verdicts(report, "ACME-2024") == [FieldVerdict.VALID]

    def test_an_aggregate_call_may_cite_any_audited_document(self, tmp_path: Path):
        """Row 7, a counter-example: the one where one call was shown every incident."""
        report = _run(tmp_path, Answers(NEIGHBOUR), mode="aggregate")

        (step,) = report.steps
        (result,) = step.results
        assert [check.verdict for check in result.checks] == [FieldVerdict.VALID]
