"""R7.41 — a `list` field is one verdict per document, however many records
answered it.

A field's percentage counts documents (R7.2). A list counted per item would
weigh a document by how many systems it names, so one incident naming nine
would outvote eight naming one. Each item's record keeps its own check, which is
what R7.42 reads.

Values are `_fixtures.md`'s "A list field".
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import (
    FieldKind,
    GoldField,
    Verdict,
    per_field,
    score_document,
)

FIELD = "affected_systems"
GROUNDED = FieldCheck(FieldVerdict.VALID)
KINDS = {"severity": FieldKind.ENUM, FIELD: FieldKind.LIST}


def answered(field: str, value: str) -> FieldRecord:
    return FieldRecord(
        field=field, value=value, source=Evidence(document="INC-4821", span=value)
    )


def scored(values: list[str], gold: dict[str, GoldField]):
    records = [answered("severity", "major"), *(answered(FIELD, value) for value in values)]
    return score_document(
        document="INC-4821",
        records=records,
        checks=[GROUNDED] * len(records),
        gold=gold,
        kinds=KINDS,
    )


GOLD = {
    "severity": GoldField(value="major"),
    FIELD: GoldField(value=["payments-api", "ledger-batch"]),
}


class TestAListIsOneVerdictPerDocument:
    """R7.41 — one verdict for the list, not one for each of its items."""

    def test_two_right_items_are_one_of_one(self):
        """Row 1 — the one where both records are right, and count once."""
        score = scored(["payments-api", "ledger-batch"], GOLD)

        verdicts = [result for result in score.results if result.field == FIELD]
        assert [result.verdict for result in verdicts] == [Verdict.CORRECT]
        (total,) = per_field([score], declared=[FIELD])
        assert (total.correct, total.scored) == (1, 1)

    def test_a_right_item_and_a_wrong_one_are_one_incorrect_verdict(self):
        """Row 2 — the one where a right item does not earn half a verdict."""
        score = scored(["payments-api", "upload-service"], GOLD)

        verdicts = [result for result in score.results if result.field == FIELD]
        assert [result.verdict for result in verdicts] == [Verdict.INCORRECT]

    def test_a_list_gold_did_not_verify_has_no_verdict(self):
        """Row 3, counter-example — the one nobody verified, not a zero (R7.3 row 4)."""
        score = scored(["payments-api", "ledger-batch"], {"severity": GoldField(value="major")})

        assert [result.field for result in score.results] == ["severity"]
        assert score.not_in_gold == (FIELD,)
