"""R6.32 — a validation failure's reason says what was wrong with the answer,
and nothing else.

Pydantic's message runs over three lines: `1 validation error for StageOutput`,
the error, the reply quoted, and a link to its documentation. The run put the
document's name in front of it, which the failure line already names. The
reason is each error pydantic found, as `location: message`, or the message
alone where the whole answer is at fault, joined by `; `.

Through `run_stage`, with a `FakeModelClient` answering both attempts and a
`FakeTracker` keeping each attempt's span: what the model answered is not lost,
it is in the spans and in the retry prompt (R6.2, R11.2).
"""

from __future__ import annotations

import json

from tests.fakes import FakeModelClient, FakeTracker

from dossier.application.extract import run_stage

DOCUMENT = "INC-4822"
TEXT = {DOCUMENT: "# INC-4822\n\nThe payment gateway timed out for two hours.\n"}
NOT_JSON = "not JSON at all"


def _failed(*replies: str, tracker: FakeTracker | None = None, lists=()):
    """`INC-4822` asked, answered with `replies` in turn; the result and the model."""
    model = FakeModelClient(responses=list(replies))
    result = run_stage(
        document=DOCUMENT,
        prompt="Extract the fields of the incident below.\n\n{{documents}}",
        schema={"type": "object"},
        model=model,
        input_documents=TEXT,
        tracker=tracker,
        lists=lists,
    )
    return result, model


def _misspelt(records: int) -> str:
    return json.dumps(
        {
            "document": DOCUMENT,
            "fields": [{"field": "severity", "valu": "major"} for _ in range(records)],
        }
    )


class TestAValidationFailureSaysWhatWasWrong:
    """R6.32 — `no valid output after 2 attempts: ` and each error, nothing else."""

    def test_an_answer_that_is_not_json(self):
        """Row 1 — the one where the model answered prose on both attempts."""
        result, _ = _failed(NOT_JSON, NOT_JSON)

        assert result.error == (
            "no valid output after 2 attempts: Invalid JSON: expected ident at line 1 column 2"
        )

    def test_every_error_is_named_where_it_is(self):
        """Row 2 — the one with a misspelt key in three records, each one named."""
        result, _ = _failed(_misspelt(3), _misspelt(3))

        assert result.error == (
            "no valid output after 2 attempts: "
            "fields.0.valu: Extra inputs are not permitted; "
            "fields.1.valu: Extra inputs are not permitted; "
            "fields.2.valu: Extra inputs are not permitted"
        )

    def test_a_field_answered_twice_is_said_in_the_runs_words(self):
        """Row 3 — the one refused by the run, not by pydantic (R6.24)."""
        twice = json.dumps(
            {
                "document": DOCUMENT,
                "fields": [
                    {"field": "severity", "value": None, "reason": "not on page 1"},
                    {"field": "severity", "value": None, "reason": "not on page 2"},
                ],
            }
        )

        result, _ = _failed(twice, twice)

        assert result.error == (
            "no valid output after 2 attempts: severity: answered more than once. "
            "Only a field declared `list` is answered once per item; answer every "
            "other field once"
        )

    def test_the_model_and_the_spans_still_get_pydantics_text(self):
        """Row 4, counter-example — the one where nothing the model said is lost."""
        tracker = FakeTracker()
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})
        tracker.start_trace(name=f"extract · {DOCUMENT}", tags={})

        _, model = _failed(NOT_JSON, NOT_JSON, tracker=tracker)

        assert "1 validation error for StageOutput" in model.calls[1]["prompt"]
        spans = [span for span in tracker.spans if span["kind"] == "llm"]
        assert len(spans) == 2
        assert all("1 validation error for StageOutput" in span["error"] for span in spans)
