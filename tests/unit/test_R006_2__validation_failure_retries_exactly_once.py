"""R6.2 — validation failure triggers exactly one retry, carrying the error, and
the retry is recorded.

One retry, because a model that cannot produce the shape twice will not produce
it on the fifth attempt either, and an unbounded retry loop turns a bad prompt
into a bill.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json

from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS

from dossier.application.extract import run_stage

PROMPT = "<source_document>{{documents}}</source_document>"
SCHEMA = {"type": "object"}

VALID = json.dumps(
    {
        "document": "INC-4821",
        "fields": [
            {
                "field": "loss_amount",
                "value": 48200.00,
                "currency": "CHF",
                "source": {"document": "INC-4821", "span": LOSS_SPAN, "page": 3},
            }
        ],
    }
)

MALFORMED = "I could not find the loss amount in this document."
WRONG_SHAPE = json.dumps({"document": "INC-4821", "extracted": []})


def run(responses: list[str]) -> tuple:
    model = FakeModelClient(responses=list(responses))
    result = run_stage(
        document="INC-4821",
        prompt=PROMPT,
        schema=SCHEMA,
        model=model,
        input_documents=STAGE_INPUTS,
    )
    return result, model


class TestRetryBudget:
    """R6.2 — one retry, and exactly one."""

    def test_an_invalid_first_answer_is_retried_once_and_succeeds(self):
        """Example 1: the one where the model gets it right the second time."""
        result, model = run([MALFORMED, VALID])

        assert model.call_count == 2
        assert result.failed is False
        assert result.attempts == 2

    def test_two_invalid_answers_stop_at_two_calls(self):
        """Example 2: the one where the budget is a budget.

        Asserted as a count rather than as "it gave up", because the count is the
        claim. A third call is money spent on a question already answered twice.
        """
        result, model = run([MALFORMED, WRONG_SHAPE])

        assert model.call_count == 2
        assert result.failed is True

    def test_a_valid_first_answer_is_not_retried(self):
        """The one where the common case costs one call.

        Without this row the rule is satisfied by always calling twice.
        """
        result, model = run([VALID])

        assert model.call_count == 1
        assert result.attempts == 1
        assert result.failed is False

    def test_the_retry_carries_the_validation_error(self):
        """Example 3: the one where the retry says what was wrong.

        Retrying with the identical prompt is asking the same question again and
        hoping, which is a coin flip with a bill attached.
        """
        _, model = run([WRONG_SHAPE, VALID])

        retry_prompt = model.calls[1]["prompt"]

        assert "validation_error" in retry_prompt
        assert retry_prompt != model.calls[0]["prompt"]

    def test_the_first_call_carries_no_correction(self):
        """The one where a first attempt is not told it failed."""
        _, model = run([VALID])

        assert "validation_error" not in model.calls[0]["prompt"]

    def test_the_attempt_count_is_recorded(self):
        """Example 2's other half: the retry is recorded, not just performed.

        R0.3 puts this in the provenance record, so someone reading an artifact
        later can see it took two goes.
        """
        result, _ = run([MALFORMED, VALID])

        assert result.attempts == 2

    def test_a_transport_error_is_not_a_validation_retry(self):
        """Counter-example (row 4): the one where the budget does not apply.

        `FakeModelClient` raises when it runs out of scripted responses, which
        stands in for a transport failure. It is a stage error, not a validation
        failure, and it must not silently consume the retry budget.
        """
        import pytest
        from tests.fakes import FakeModelClientError

        model = FakeModelClient(responses=[])

        with pytest.raises(FakeModelClientError):
            run_stage(
                document="INC-4821",
                prompt=PROMPT,
                schema=SCHEMA,
                model=model,
                input_documents=STAGE_INPUTS,
            )
