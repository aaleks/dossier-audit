"""R0.14 — a field-record artifact is written as indented JSON, one key per line,
ending in a newline.

The serialiser R0.11's two copies are both made with. Tested here rather than
through the CLI because it is one function and one decision: the acceptance test
for R0.11 already proves the run copy and the cache entry are the same bytes, and
this proves what those bytes are.
"""

from __future__ import annotations

import json


def _result(document: str, records=()):
    from dossier.application.extract import DocumentResult

    return DocumentResult(document=document, records=tuple(records))


def _record(field: str, value, span: str):
    from dossier.domain.schemas import FieldRecord

    return FieldRecord.model_validate(
        {
            "field": field,
            "value": value,
            "source": {"document": "PLAY-1001.md", "span": span, "page": None},
        }
    )


class TestAFieldRecordArtifactIsIndentedJson:
    """R0.14 — the file a reviewer opens is a file a reviewer can read."""

    def test_it_is_indented_two_spaces_and_ends_in_a_newline(self):
        """The one from row 1: four records, and none of them on the same line."""
        from dossier.application.run import _as_text

        text = _as_text(
            _result(
                "PLAY-1001.md",
                [
                    _record("loss_amount", 18400.0, "a recorded loss of CHF 18'400"),
                    _record("severity", "major", "**Severity:** major"),
                ],
            )
        )

        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        assert '\n  "document": "PLAY-1001.md"' in text
        assert '\n  "fields": [' in text
        # The property that makes it readable at all: a key and its value on
        # a line of their own, rather than every record run together on one.
        assert '"field": "loss_amount"' in text
        assert '"field":"loss_amount"' not in text

    def test_it_round_trips_to_the_records_it_was_made_from(self):
        """Formatting is a format. The artifact still parses to what it holds."""
        from dossier.application.run import _as_text

        text = _as_text(
            _result("PLAY-1001.md", [_record("severity", "major", "**Severity:** major")])
        )

        assert json.loads(text) == {
            "document": "PLAY-1001.md",
            "fields": [
                {
                    "field": "severity",
                    "value": "major",
                    "currency": None,
                    "reason": None,
                    "confidence": None,
                    "source": {
                        "document": "PLAY-1001.md",
                        "span": "**Severity:** major",
                        "page": None,
                    },
                }
            ],
        }

    def test_document_precedes_fields_rather_than_being_sorted(self):
        """Row 4 — an empty `fields` list is still a record, in declared order.

        Sorting the keys would put `document` after `fields` and would be a
        second, invisible decision taken for the sake of a first.
        """
        from dossier.application.run import _as_text

        text = _as_text(_result("PLAY-1001.md"))

        assert text.index('"document"') < text.index('"fields"')
        assert json.loads(text) == {"document": "PLAY-1001.md", "fields": []}

    def test_prose_from_a_step_with_no_output_is_untouched(self):
        """Row 5 — a `report` step's artifact is what the model wrote.

        No newline appended and no formatting applied: there is no JSON here to
        indent, and appending to prose would change an artifact nobody asked to
        change.
        """
        from dossier.application.extract import DocumentResult
        from dossier.application.run import _as_text

        prose = "The quarter's incidents cluster on the payment path."
        assert _as_text(DocumentResult(document="*", text=prose)) == prose
