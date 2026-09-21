"""R012.2 — a record's only input is the document key, its expectations are the
verified answers, and its snapshot is a tag.

A pure projection: a `GoldDocument` and the snapshot address it is held at go in,
one MLflow dataset record comes out. No workspace, no server, no clock.

The values are `INC-4821`'s from `specs/_fixtures.md` — CHF 48'200, resolved
2026-07-28, `major` — and the snapshot `a3f9c1e2` it is held at.
"""

from __future__ import annotations

from datetime import date

from dossier.domain.gold import GoldDocument

SNAPSHOT = "a3f9c1e2" * 8  # a real address carries all 64 characters (R0.7)


def _incident() -> GoldDocument:
    """`INC-4821` as a reviewer verified it, with the three fields row 1 names."""
    return GoldDocument(
        document="INC-4821",
        verified_by="a.aleks",
        verified_at=date(2026, 8, 14),
        fields={
            "loss_amount": {"value": 48200.00, "currency": "CHF"},
            "resolution_date": {"value": "2026-07-28"},
            "severity": {"value": "major"},
        },
    )


class TestARecordHoldsTheDocumentAndItsVerifiedAnswers:
    """R12.2 — a record's only input is the document key, and its snapshot is a tag."""

    def test_the_document_is_the_only_input_and_the_answers_are_the_expectations(self):
        """Example 1: the one where a verified document becomes one record.

        The document key alone in `inputs`, because MLflow merges a record onto
        the hash of its `inputs` and that is what makes the document the merge
        key (R12.3). The snapshot rides along as a tag, where changing it updates
        the record a person already has rather than adding a second one.
        """
        from dossier.domain.datasets import record_for

        record = record_for(_incident(), snapshot=SNAPSHOT)

        assert record == {
            "inputs": {"document": "INC-4821"},
            "expectations": {
                "loss_amount": 48200.00,
                "resolution_date": "2026-07-28",
                "severity": "major",
            },
            "tags": {"dossier.snapshot": SNAPSHOT},
        }

    def test_a_verified_abstention_is_carried_as_a_null_expectation(self):
        """Example 2: the one where the reviewer verified that there is no answer.

        `INC-5455`'s root cause is undetermined in the document itself, and a
        reviewer said so (R7.3). Dropping the field would make it read as one
        nobody verified, and those two want different work (R7.3 row 4) — so the
        null is present rather than absent.
        """
        from dossier.domain.datasets import record_for

        undetermined = GoldDocument(
            document="INC-5455",
            verified_by="a.aleks",
            verified_at=date(2026, 8, 14),
            fields={
                "severity": {"value": "major"},
                "root_cause": {"value": None, "reason": "only competing hypotheses"},
            },
        )

        record = record_for(undetermined, snapshot=SNAPSHOT)

        assert record["expectations"] == {"severity": "major", "root_cause": None}
        assert "root_cause" in record["expectations"], "verified as absent, not unverified"

    def test_a_document_the_ledger_has_no_row_for_publishes_without_the_tag(self):
        """Example 3: the one verified before anything was synced.

        The snapshot is provenance for the answers, not a precondition for having
        them. A gold set written ahead of the first sync publishes; it simply
        cannot say which bytes it was checked against yet.
        """
        from dossier.domain.datasets import record_for

        record = record_for(_incident(), snapshot=None)

        assert record["inputs"] == {"document": "INC-4821"}
        assert "tags" not in record

    def test_the_reviewer_and_the_date_are_not_expectations(self):
        """Counter-example (row 4): the one where attribution stays out of the answers.

        `verified_by` and `verified_at` are attribution for the set — carried as
        dataset tags (R12.1) — and an expectation is something a run can be wrong
        about. No run is wrong about who verified the gold.
        """
        from dossier.domain.datasets import record_for

        record = record_for(_incident(), snapshot=SNAPSHOT)

        assert "verified_by" not in record["expectations"]
        assert "verified_at" not in record["expectations"]
        assert "verified_by" not in record["inputs"]

    def test_the_currency_beside_an_amount_is_not_a_second_expectation(self):
        """The one where a field's metadata does not become a field of its own.

        `loss_amount` is verified as `{"value": 48200.00, "currency": "CHF"}`, and
        the answer is the value. A `loss_amount.currency` expectation would be a
        field no run ever answers and no scorer ever reads (R7.1).
        """
        from dossier.domain.datasets import record_for

        record = record_for(_incident(), snapshot=SNAPSHOT)

        assert record["expectations"]["loss_amount"] == 48200.00
        assert list(record["expectations"]) == ["loss_amount", "resolution_date", "severity"]
