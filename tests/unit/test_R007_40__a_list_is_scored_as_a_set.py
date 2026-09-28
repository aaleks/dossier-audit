"""R7.40 — a `list` field is correct when the run's items and gold's items are
the same set.

A list is answered one record per item (spec 006), so its answer is the values
of its records. Order is not information, and neither is a system named on two
pages twice; an item is compared as a `reference` is, case folded, and matches
whole. The one worth watching is row 6: a scorer comparing by substring would
read `payments` as `payments-api` and call a wrong answer right.

Values are `_fixtures.md`'s "A list field".
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import GoldField, Verdict, score_list

FIELD = "affected_systems"
GROUNDED = FieldCheck(FieldVerdict.VALID)
BOTH = ["payments-api", "ledger-batch"]


def item(value: str) -> FieldRecord:
    return FieldRecord(
        field=FIELD, value=value, source=Evidence(document="INC-4821", span=value)
    )


def scored(values: list[str], gold: list[str] | None = BOTH):
    records = [item(value) for value in values]
    return score_list(
        field=FIELD,
        records=records,
        checks=[GROUNDED] * len(records),
        gold=GoldField(value=gold),
    )


class TestAListIsScoredAsASet:
    """R7.40 — the same set of items, and nothing else, is the same answer."""

    def test_the_same_items_are_correct(self):
        """Row 1 — the one where both systems are named."""
        score = scored(["payments-api", "ledger-batch"])

        assert score.field == FIELD
        assert score.verdict is Verdict.CORRECT

    def test_order_and_case_are_not_information(self):
        """Row 2 — the one named the other way round, in another case."""
        assert scored(["ledger-batch", "Payments-API"]).verdict is Verdict.CORRECT

    def test_a_system_named_twice_is_one_system(self):
        """Row 3 — the one where two pages name the same system."""
        score = scored(["payments-api", "payments-api", "ledger-batch"])

        assert score.verdict is Verdict.CORRECT

    def test_a_missing_item_is_named(self):
        """Row 4 — the one that missed a system."""
        score = scored(["payments-api"])

        assert score.verdict is Verdict.INCORRECT
        assert "missing: ledger-batch" in score.detail
        assert "not in gold" not in score.detail

    def test_an_item_gold_does_not_have_is_named(self):
        """Row 5 — the one that named a system gold does not."""
        score = scored(["payments-api", "ledger-batch", "upload-service"])

        assert score.verdict is Verdict.INCORRECT
        assert "not in gold: upload-service" in score.detail
        assert "missing" not in score.detail

    def test_an_item_matches_whole(self):
        """Row 6, counter-example — the one where `payments` is not `payments-api`."""
        score = scored(["payments"], gold=["payments-api"])

        assert score.verdict is Verdict.INCORRECT
        assert "missing: payments-api" in score.detail
        assert "not in gold: payments" in score.detail

    def test_an_abstention_against_a_gold_null_is_correct(self):
        """Row 7, counter-example — the one where nothing is stated, and gold agrees (R7.3)."""
        abstains = FieldRecord(field=FIELD, value=None, reason="not stated in document")

        score = score_list(
            field=FIELD,
            records=[abstains],
            checks=[FieldCheck(FieldVerdict.ABSTAINED, "not stated in document")],
            gold=GoldField(value=None),
        )

        assert score.verdict is Verdict.CORRECT
