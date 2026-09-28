"""R6.24 — only a `list` field may be answered by more than one record in one
answer.

A `list` is answered one record per item, each grounded on its own span (spec
006, "A list is answered one record per item"). Any other field answered twice
is two answers to one question, and nothing downstream could say which the model
meant -- so it is refused on the reply, where the one retry can still put it
right (R6.2), and a second refusal fails the document alone (R6.9).

The document is `INC-4821` as `tests/scoring_example.py` holds it: its
"Affected systems:" line names both systems, and its exposure is CHF 48'200.
"""

from __future__ import annotations

import json

from tests.fakes import FakeModelClient
from tests.scoring_example import ISSUES, abstains, found

from dossier.application.extract import run_stage
from dossier.domain.grounding import FieldVerdict

SCHEMA = {"type": "object"}
LISTS = frozenset({"affected_systems"})
PROMPT = "Extract the requested fields.\n\n{text}"
DOCUMENTS = {document: ISSUES[document] for document in ("INC-4821", "INC-4822")}


def answer(document: str, *fields: dict) -> str:
    return json.dumps({"document": document, "fields": list(fields)})


def asked(document: str, *replies: str):
    model = FakeModelClient(responses=list(replies))
    result = run_stage(
        document=document,
        prompt=PROMPT.format(text=DOCUMENTS[document]),
        schema=SCHEMA,
        model=model,
        input_documents={document: DOCUMENTS[document]},
        lists=LISTS,
    )
    return result, model


def loss(written: str) -> dict:
    return found("INC-4821", "loss_amount", 48200.00, f"exposure CHF {written}", currency="CHF")


class TestOnlyAListFieldIsAnsweredMoreThanOnce:
    """R6.24 — one record per item for a list, and one answer for everything else."""

    def test_a_list_answered_one_record_per_item_is_valid(self):
        """Row 1 — the one where each system has its own span."""
        result, model = asked(
            "INC-4821",
            answer(
                "INC-4821",
                found("INC-4821", "affected_systems", "payments-api", "payments-api"),
                found("INC-4821", "affected_systems", "ledger-batch", "ledger-batch"),
            ),
        )

        assert not result.failed
        assert [record.value for record in result.records] == ["payments-api", "ledger-batch"]
        assert [check.verdict for check in result.checks] == [FieldVerdict.VALID] * 2
        assert model.call_count == 1

    def test_a_list_of_one_is_one_record(self):
        """Row 2 — the one where INC-4822 names one system."""
        result, _ = asked(
            "INC-4822",
            answer(
                "INC-4822",
                found("INC-4822", "affected_systems", "ledger-batch", "ledger-batch"),
            ),
        )

        assert not result.failed
        assert len(result.records) == 1

    def test_an_amount_answered_twice_is_refused_and_retried_once(self):
        """Row 3, counter-example — the one where the amount is answered twice."""
        twice = answer("INC-4821", loss("48'200"), loss("48'200"), abstains("root_cause"))

        result, model = asked("INC-4821", twice, twice)

        assert result.failed
        assert result.records == ()
        assert "loss_amount" in result.error
        # One retry, and it carried the refusal (R6.2).
        assert model.call_count == 2
        assert "loss_amount" in model.calls[1]["prompt"]
        assert "loss_amount" not in model.calls[0]["prompt"]

    def test_a_retry_that_answers_once_stands(self):
        """Row 3, continued — the one the retry puts right."""
        once = answer("INC-4821", loss("48'200"))

        result, model = asked(
            "INC-4821", answer("INC-4821", loss("48'200"), loss("48'200")), once
        )

        assert not result.failed
        assert result.attempts == 2
        assert [record.field for record in result.records] == ["loss_amount"]

    def test_each_page_of_a_per_part_step_answering_once_is_valid(self):
        """Row 4, counter-example — the one where each page is its own answer (R3.12)."""
        first, _ = asked("INC-4821", answer("INC-4821", loss("48'200")))
        second, _ = asked("INC-4821", answer("INC-4821", loss("48'200")))

        assert not first.failed and not second.failed

    def test_an_array_in_one_record_fails_validation_as_before(self):
        """Row 5, counter-example — the one where the model sends an array."""
        array = answer(
            "INC-4821",
            found(
                "INC-4821", "affected_systems", ["payments-api", "ledger-batch"], "payments-api"
            ),
        )

        result, model = asked("INC-4821", array, array)

        assert result.failed
        assert model.call_count == 2
