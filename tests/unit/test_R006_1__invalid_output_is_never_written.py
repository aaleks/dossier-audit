"""R6.1 — output that does not validate against its schema is never written and
never cached.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json

import pytest
from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS

from dossier.application.extract import run_stage

PROMPT = "<source_document>{{documents}}</source_document>"
SCHEMA = {"type": "object"}


def valid(**overrides) -> str:
    field = {
        "field": "loss_amount",
        "value": 48200.00,
        "currency": "CHF",
        "source": {"document": "INC-4821", "span": LOSS_SPAN, "page": 3},
    } | overrides
    return json.dumps({"document": "INC-4821", "fields": [field]})


def run(responses: list[str]):
    return run_stage(
        document="INC-4821",
        prompt=PROMPT,
        schema=SCHEMA,
        model=FakeModelClient(responses=list(responses)),
        input_documents=STAGE_INPUTS,
    )


class TestInvalidOutputIsNeverWritten:
    """R6.1 — nothing malformed reaches disk or the cache."""

    def test_a_wrongly_typed_value_fails_the_document(self):
        """Example 1: the one where the model answered in prose.

        `"quite a lot"` against a numeric field, twice. Nothing to write, nothing
        to cache, and the document reported as failed.
        """
        wrong_type = json.dumps(
            {"document": "INC-4821", "fields": [{"field": "loss_amount", "value": []}]}
        )

        result = run([wrong_type, wrong_type])

        assert result.failed
        assert result.records == ()

    def test_an_unknown_extra_field_is_rejected(self):
        """Example 2: the one where the schema is closed.

        A field nobody declared is a silent contract change. Accepting it means
        the next reader of this artifact sees data that no schema describes and
        no scorer will ever look at.
        """
        extra = json.dumps({"document": "INC-4821", "fields": [], "confidence_overall": "high"})

        assert run([extra, extra]).failed

    def test_prose_instead_of_json_is_rejected(self):
        """Example 3: the one where the answer is not JSON at all.

        Counted as a validation failure for retry purposes, so the model gets one
        chance to be told it must return JSON (R6.2).
        """
        result = run(["I could not find the loss amount.", valid()])

        assert result.failed is False
        assert result.attempts == 2

    def test_a_failed_document_produces_no_records_to_write(self):
        """The one that makes "never written" checkable here.

        This layer decides *what* there is to write. A result carrying no records
        and an error is what stops the caller writing anything, which is where
        R6.1 and R5.8 meet: no artifact, therefore no cache entry.
        """
        result = run(["nonsense", "still nonsense"])

        assert result.failed
        assert result.records == ()
        assert result.checks == ()

    def test_abstention_is_written_and_cached(self):
        """Counter-example (row 4): the one where null is conforming output.

        `root_cause: null` with a reason validates, produces a record, and is
        cached like any other answer (R6.5).
        """
        abstained = json.dumps(
            {
                "document": "INC-4821",
                "fields": [
                    {
                        "field": "root_cause",
                        "value": None,
                        "reason": "not stated in document",
                        "confidence": "none",
                    }
                ],
            }
        )

        result = run([abstained])

        assert result.failed is False
        assert len(result.records) == 1

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param("", id="empty"),
            pytest.param("null", id="json-null"),
            pytest.param("[]", id="json-list"),
            pytest.param('{"fields": []}', id="missing-document"),
        ],
    )
    def test_shapes_that_are_not_a_stage_output_are_rejected(self, response: str):
        """The boundaries around "does not validate".

        Each is JSON-ish and none is a stage output. An empty response in
        particular would be easy to read as "no fields found", which is not the
        same as abstaining and must not be treated as it.
        """
        assert run([response, response]).failed
