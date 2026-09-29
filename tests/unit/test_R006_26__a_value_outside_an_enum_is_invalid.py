"""R6.26 — an `enum` field answered with a value outside its declared values is
`invalid`, naming them, and the rest of the answer stands.

A provider that reads the schema as guidance (R6.25) can still answer outside
it. That is a finding about one field, like a value with no source (R6.6), not a
validation failure: `SEV-1` is one answer, plainly meant, and not an allowed
one. `_fixtures.md`'s `INC-4830` prints `SEV-1` on every page, and gold's
`critical` is a reviewer's reading of it.

The decision is the domain's (`check_field`); then the run, through `execute`,
its cache and a replay -- the reading `dossier eval` scores -- because a check
nothing hands the vocabulary to is a check that never fires.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for

from dossier.application.manifest import Manifest
from dossier.application.run import RunInputs, execute, replay
from dossier.domain.fields import OutputSchema
from dossier.domain.grounding import FieldVerdict, check_field
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.schemas import FieldRecord

POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
TEXT = {POSTMORTEM: "SEV-1 | Checkout TLS expiry\nResolved 2026-07-28 07:04 CEST"}
ENUMS = {"severity": ("minor", "major", "critical")}
FINDING = "severity: 'SEV-1' is not one of minor, major, critical"


def _said(field: str, value: str, span: str) -> FieldRecord:
    return FieldRecord.model_validate(
        {"field": field, "value": value, "source": {"document": POSTMORTEM, "span": span}}
    )


def _checked(record: FieldRecord):
    return check_field(record, input_documents=TEXT, enums=ENUMS)


class TestWhatAValueOutsideAnEnumIs:
    """R6.26 — the check: an enum's value is one of its values, case folded."""

    def test_the_header_quoted_for_the_vocabulary_is_invalid(self):
        """Row 1 — the one where `SEV-1` is grounded, and still not an allowed value."""
        check = _checked(_said("severity", "SEV-1", "SEV-1"))

        assert check.verdict is FieldVerdict.INVALID
        assert check.detail == FINDING

    def test_only_the_case_differing_is_valid(self):
        """Row 2 — the one where `Critical` is `critical`, as the scorer compares it."""
        assert _checked(_said("severity", "Critical", "SEV-1")).verdict is FieldVerdict.VALID

    def test_a_field_that_is_not_an_enum_is_not_held_to_one(self):
        """Row 1, its other half — the one where `resolution_date` is checked as before."""
        check = _checked(_said("resolution_date", "2026-07-28", "Resolved 2026-07-28"))

        assert check.verdict is FieldVerdict.VALID

    def test_an_abstention_is_not_outside_the_vocabulary(self):
        """Row 4, counter-example — the one where the page honestly says nothing (R6.5)."""
        silent = FieldRecord(field="severity", value=None, reason="not on this page")

        assert _checked(silent).verdict is FieldVerdict.ABSTAINED


def _run(workspace: Path, model: FakeModelClient, *, run_id: str):
    """One `extract` step over the postmortem's text, `severity` declared an enum."""
    from dossier.infrastructure.cache import ArtifactCache

    return execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit",
                sources=["postmortems"],
                model="anthropic:claude-sonnet-4-5-20250929",
                steps=[
                    StepConfig(
                        id="extract",
                        prompt="prompts/extract.md",
                        input="documents",
                        mode="per_file",
                        output="schemas/incident.yaml",
                    )
                ],
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="6e0d4b27" * 8, enums=ENUMS
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents={key: sha256(text.encode()).hexdigest() for key, text in TEXT.items()},
            document_text=TEXT,
            document_content={"markdown": TEXT},
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 9, 29, 8, 0, tzinfo=UTC),
        dossier_version="0.1.0",
    )


ANSWER = json.dumps(
    {
        "document": POSTMORTEM,
        "fields": [
            {
                "field": "severity",
                "value": "SEV-1",
                "source": {"document": POSTMORTEM, "span": "SEV-1"},
            },
            {
                "field": "resolution_date",
                "value": "2026-07-28",
                "source": {"document": POSTMORTEM, "span": "Resolved 2026-07-28"},
            },
        ],
    }
)


def _verdicts(report) -> dict[str, tuple[FieldVerdict, str | None]]:
    (step,) = report.steps
    (result,) = step.results
    assert not result.failed, result.error
    return {
        record.field: (check.verdict, check.detail)
        for record, check in zip(result.records, result.checks, strict=True)
    }


class TestARunNamesIt:
    """R6.26 — through the run: the finding, the rest of the answer, on every read."""

    def test_the_finding_is_named_and_the_rest_of_the_answer_stands(self, tmp_path: Path):
        """Row 1 — the one where the document is not failed for one field."""
        report = _run(
            tmp_path, FakeModelClient(responses=[ANSWER]), run_id="20260929T080000Z-aaaa"
        )

        verdicts = _verdicts(report)
        assert verdicts["severity"] == (FieldVerdict.INVALID, FINDING)
        assert verdicts["resolution_date"][0] is FieldVerdict.VALID

    def test_a_cached_answer_and_its_replay_are_read_the_same_way(self, tmp_path: Path):
        """Row 3 — the one where a written answer is checked again, with no model asked."""
        from dossier.infrastructure.cache import ArtifactCache

        _run(tmp_path, FakeModelClient(responses=[ANSWER]), run_id="20260929T080000Z-aaaa")
        again = FakeModelClient(responses=[])
        served = _run(tmp_path, again, run_id="20260929T080100Z-bbbb")
        replayed = replay(
            manifest=Manifest.read(served.manifest_path),
            document_text=TEXT,
            cache=ArtifactCache(tmp_path, namespace="stage"),
            enums={"extract": ENUMS},
        )

        assert again.call_count == 0
        assert _verdicts(served)["severity"] == (FieldVerdict.INVALID, FINDING)
        assert _verdicts(replayed)["severity"] == (FieldVerdict.INVALID, FINDING)
