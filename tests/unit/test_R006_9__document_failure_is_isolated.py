"""R6.9 — a document that fails after retry does not abort the run and does not
poison the cache for other documents.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS

from dossier.application.extract import DocumentResult, run_stage

PROMPT = "<source_document>{{documents}}</source_document>"
SCHEMA = {"type": "object"}

NONSENSE = "no JSON here"


def valid_for(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "loss_amount",
                    "value": 48200.00,
                    "currency": "CHF",
                    "source": {"document": "INC-4821", "span": LOSS_SPAN},
                }
            ],
        }
    )


def run_batch(documents: list[str], responses: list[str]) -> list[DocumentResult]:
    """Run one stage over several documents against a single scripted client."""
    model = FakeModelClient(responses=list(responses))
    return [
        run_stage(
            document=document,
            prompt=PROMPT,
            schema=SCHEMA,
            model=model,
            input_documents=STAGE_INPUTS,
        )
        for document in documents
    ]


class TestDocumentFailureIsIsolated:
    """R6.9 — one bad document is one bad document."""

    def test_a_failing_document_does_not_stop_the_others(self):
        """Example 1: the one where 20 of 21 complete.

        `INC-4822` fails twice; the documents on either side of it are unaffected
        and produce their records normally.
        """
        results = run_batch(
            ["INC-4821", "INC-4822", "INC-4901"],
            [valid_for("INC-4821"), NONSENSE, NONSENSE, valid_for("INC-4901")],
        )

        assert [result.failed for result in results] == [False, True, False]

    def test_the_run_can_report_exactly_which_document_failed(self):
        """Example 2: the one where the run exits non-zero and says why.

        The error names the document. A run that reported "1 failed" without
        saying which would send someone to read 21 artifacts to find out.
        """
        results = run_batch(
            ["INC-4821", "INC-4822"], [valid_for("INC-4821"), NONSENSE, NONSENSE]
        )

        failures = [result for result in results if result.failed]

        assert len(failures) == 1
        assert "INC-4822" in failures[0].error

    def test_a_failed_document_carries_nothing_cacheable(self):
        """Example 3's precondition: the one where nothing is left behind.

        The failed document has no records and no checks, so a caller has nothing
        to write for it. That is what lets the next run recompute only that
        document once the prompt is fixed (R5.7, R5.8).
        """
        results = run_batch(
            ["INC-4821", "INC-4822"], [valid_for("INC-4821"), NONSENSE, NONSENSE]
        )

        succeeded, failed = results

        assert failed.records == ()
        assert succeeded.records != ()

    def test_a_document_with_ungrounded_fields_has_not_failed(self):
        """Counter-example: the one where findings are not failures.

        A field whose span cannot be located is a finding for review (R6.4), not
        a reason to discard the document. Conflating the two would throw away
        every other field in the same answer.
        """
        ungrounded = json.dumps(
            {
                "document": "INC-4821",
                "fields": [
                    {
                        "field": "loss_amount",
                        "value": 48200.00,
                        "source": {
                            "document": "INC-4821",
                            "span": "total exposure CHF 48,200",
                        },
                    }
                ],
            }
        )

        (result,) = run_batch(["INC-4821"], [ungrounded])

        assert result.failed is False
        assert len(result.field_failures) == 1

    def test_each_document_gets_its_own_retry_budget(self):
        """The one where one document's failure does not spend another's.

        Two documents, each allowed two attempts. A shared budget would let the
        first failure starve every document after it.
        """
        model = FakeModelClient(responses=[NONSENSE, NONSENSE, NONSENSE, valid_for("B")])

        first = run_stage(
            document="A",
            prompt=PROMPT,
            schema=SCHEMA,
            model=model,
            input_documents=STAGE_INPUTS,
        )
        second = run_stage(
            document="B",
            prompt=PROMPT,
            schema=SCHEMA,
            model=model,
            input_documents=STAGE_INPUTS,
        )

        assert first.failed is True
        assert second.failed is False
        assert second.attempts == 2
