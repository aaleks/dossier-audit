"""R7.42 — an ungrounded item makes its list incorrect, even when every value
matches gold.

R7.4 for each item. A list is answered one record per item precisely so each
item carries its own evidence (spec 006), and a system the document never names
cannot shelter behind the span of one it does. A list is not more right for
being mostly grounded.

Values are `_fixtures.md`'s "A list field".
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import GoldField, Verdict, score_list

FIELD = "affected_systems"
GOLD = GoldField(value=["payments-api", "ledger-batch"])
GROUNDED = FieldCheck(FieldVerdict.VALID)


def item(value: str, document: str = "INC-4821") -> FieldRecord:
    return FieldRecord(field=FIELD, value=value, source=Evidence(document=document, span=value))


def scored(records: list[FieldRecord], checks: list[FieldCheck]):
    return score_list(field=FIELD, records=records, checks=checks, gold=GOLD)


class TestAnUngroundedItemFailsItsList:
    """R7.42 — every item's evidence holds, or the list is incorrect."""

    def test_one_ungrounded_item_fails_the_list(self):
        """Row 1 — the one where the right systems are named and one is not shown."""
        ungrounded = FieldCheck(
            FieldVerdict.UNGROUNDED, f"{FIELD}: span not found in INC-4821 (R6.4)."
        )

        score = scored([item("payments-api"), item("ledger-batch")], [GROUNDED, ungrounded])

        assert score.verdict is Verdict.INCORRECT
        assert "ungrounded: ledger-batch" in score.detail
        assert "payments-api" not in score.detail

    def test_an_item_citing_another_document_fails_the_list(self):
        """Row 2 — the one where an item cites a document its call never read (R6.23)."""
        invalid = FieldCheck(
            FieldVerdict.INVALID,
            f"{FIELD}: cites 'INC-4822', which was not an input to this stage.",
        )

        score = scored(
            [item("payments-api"), item("ledger-batch", document="INC-4822")],
            [GROUNDED, invalid],
        )

        assert score.verdict is Verdict.INCORRECT
        assert "cites 'INC-4822'" in score.detail

    def test_an_abstaining_record_beside_grounded_items_is_not_a_failure(self):
        """Row 3, counter-example — the one where an abstention sits beside the items (R6.5)."""
        abstains = FieldRecord(field=FIELD, value=None, reason="no other system named")

        score = scored(
            [item("payments-api"), abstains, item("ledger-batch")],
            [GROUNDED, FieldCheck(FieldVerdict.ABSTAINED, "no other system named"), GROUNDED],
        )

        assert score.verdict is Verdict.CORRECT
