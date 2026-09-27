"""R6.22 — a `per_group` field cites a member of its group.

A group has no text of its own; its members do. A field answered from a group
names the member its span is in, and R6.4 looks for the span there. A citation
of another group's document is one the call never read, so it is invalid, as
R6.3 says of any document that was not an input: worse than no citation,
because it looks checkable.

Run through `execute`, because which documents a call read is a fact about the
run, not about the field: `check_field` is right when handed the right
documents, and this proves a group's call hands it its members and no others.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.pipelines import prompt_for

from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.grounding import FieldVerdict
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
CONTRACTS = {
    "ACME-2024/amendment-3.pdf": "Amendment 3 extends the term to 2027-03-31.",
    "ACME-2024/master.pdf": "Liability is capped at EUR 2,000,000.",
    "GLOBEX-2023/master.pdf": "The term ends 2026-12-31.",
}


def _cited(document: str, field: str, value, span: str) -> dict:
    return {"field": field, "value": value, "source": {"document": document, "span": span}}


class Answers:
    """Answers each group's call with the fields scripted for that group."""

    model_id = MODEL

    def __init__(self, fields: dict[str, list[dict]]) -> None:
        self.fields = fields

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        group = next(
            name
            for name in self.fields
            if f'<document key="{name}/' in prompt or f'<document key="{name}">' in prompt
        )
        return json.dumps({"document": group, "fields": self.fields[group]})


def _verdicts(tmp_path: Path, text: dict[str, str], model) -> dict:
    """Each group's field verdicts, from one run of a `per_group` step."""
    config = PipelineConfig(
        name="contract-renewal",
        sources=["contracts"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract", prompt="prompts/extract.md", input="documents", mode="per_group"
            )
        ],
    )
    report = execute(
        workspace=tmp_path,
        pipeline=config,
        pipeline_hash="0e52dd18" * 8,
        documents={key: sha256(body.encode()).hexdigest() for key, body in text.items()},
        document_text=text,
        schemas={"extract": SCHEMA},
        prompts={"extract": prompt_for(["documents"])},
        model=model,
        cache=ArtifactCache(tmp_path, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )
    (step,) = report.steps
    return {
        result.document: {
            record.field: check.verdict
            for record, check in zip(result.records, result.checks, strict=True)
        }
        for result in step.results
    }


class TestAGroupFieldCitesAMember:
    """R6.22 — a field answered from a group cites one of its members."""

    def test_one_answer_cites_two_members_and_both_are_grounded(self, tmp_path: Path):
        """Rows 1 and 2: the one where the date and the cap are in different files."""
        verdicts = _verdicts(
            tmp_path,
            CONTRACTS,
            Answers(
                {
                    "ACME-2024": [
                        _cited(
                            "ACME-2024/amendment-3.pdf",
                            "renewal_date",
                            "2027-03-31",
                            "2027-03-31",
                        ),
                        _cited(
                            "ACME-2024/master.pdf", "liability_cap", 2000000, "EUR 2,000,000"
                        ),
                    ],
                    "GLOBEX-2023": [],
                }
            ),
        )

        assert verdicts["ACME-2024"] == {
            "renewal_date": FieldVerdict.VALID,
            "liability_cap": FieldVerdict.VALID,
        }

    def test_citing_another_groups_document_is_invalid(self, tmp_path: Path):
        """Row 3: the one where ACME's answer quotes GLOBEX's contract.

        The span is really there, in `GLOBEX-2023/master.pdf`. That is what makes
        it dangerous: a reviewer would find the quote and never notice the call
        that produced it was never shown that document.
        """
        verdicts = _verdicts(
            tmp_path,
            CONTRACTS,
            Answers(
                {
                    "ACME-2024": [
                        _cited(
                            "GLOBEX-2023/master.pdf", "renewal_date", "2026-12-31", "2026-12-31"
                        )
                    ],
                    "GLOBEX-2023": [],
                }
            ),
        )

        assert verdicts["ACME-2024"] == {"renewal_date": FieldVerdict.INVALID}

    def test_citing_the_groups_own_name_is_invalid(self, tmp_path: Path):
        """Row 4: the one that names the contract rather than a file of it.

        No member is keyed `ACME-2024`, so there is no text in which the span
        could be found or not.
        """
        verdicts = _verdicts(
            tmp_path,
            CONTRACTS,
            Answers(
                {
                    "ACME-2024": [
                        _cited("ACME-2024", "renewal_date", "2027-03-31", "2027-03-31")
                    ],
                    "GLOBEX-2023": [],
                }
            ),
        )

        assert verdicts["ACME-2024"] == {"renewal_date": FieldVerdict.INVALID}

    def test_an_issue_is_a_member_of_its_own_group(self, tmp_path: Path):
        """Row 5, a counter-example: the one where the group's name is a member's too.

        The Jira issue `INC-4821` is itself a member of group `INC-4821`, beside
        its attachment, so citing it is citing a document the call read.
        """
        issue = {
            "INC-4821": "Finance confirmed a total exposure CHF 48'200.",
            "INC-4821/report.pdf": "The report repeats the figure.",
        }

        verdicts = _verdicts(
            tmp_path,
            issue,
            Answers(
                {
                    "INC-4821": [
                        _cited("INC-4821", "loss_amount", 48200.0, "total exposure CHF 48'200")
                    ]
                }
            ),
        )

        assert verdicts["INC-4821"] == {"loss_amount": FieldVerdict.VALID}
