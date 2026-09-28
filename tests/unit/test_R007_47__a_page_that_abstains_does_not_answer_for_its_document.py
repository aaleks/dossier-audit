"""R7.47 — a page that abstains does not answer for its document while another
of its pages gives a value.

"Not on this page" is a fact about the page, not about the document. The
document abstains only when every page did, and is then scored as any
abstention is (R7.3). The values are `_fixtures.md`'s "`INC-4830` page by page".
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import FieldKind, GoldField, Verdict, score_document

POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
GROUNDED = FieldCheck(FieldVerdict.VALID)
KINDS = {"resolution_date": FieldKind.DATE}
PAGES = ("page-001.png", "page-002.png", "page-003.png")


def answered(value: str) -> FieldRecord:
    return FieldRecord(
        field="resolution_date", value=value, source=Evidence(document=POSTMORTEM, span=value)
    )


def abstained() -> FieldRecord:
    return FieldRecord(field="resolution_date", value=None, reason="not on this page")


def verdict_of(records: list[FieldRecord], gold: str | None):
    (result,) = score_document(
        document=POSTMORTEM,
        records=records,
        checks=[GROUNDED] * len(records),
        parts=PAGES[: len(records)],
        gold={"resolution_date": GoldField(value=gold)},
        kinds=KINDS,
    ).results
    return result


class TestAPageThatAbstainsDoesNotAnswerForItsDocument:
    """R7.47 — "not on this page" is not "not in the document"."""

    def test_pages_that_abstain_beside_one_that_answers_are_left_out(self):
        """Row 1 — the one where page 1 states the date and pages 2 and 3 do not."""
        result = verdict_of([answered("2026-07-28"), abstained(), abstained()], "2026-07-28")

        assert result.verdict is Verdict.CORRECT

    def test_every_page_abstaining_against_a_gold_null_is_correct(self):
        """Row 2 — the one where the document abstains, and so does gold."""
        result = verdict_of([abstained(), abstained(), abstained()], None)

        assert result.verdict is Verdict.CORRECT

    def test_every_page_abstaining_against_a_gold_value_is_incorrect(self):
        """Row 3, counter-example — the one where the abstention is the document's answer."""
        result = verdict_of([abstained(), abstained(), abstained()], "2026-07-28")

        assert result.verdict is Verdict.INCORRECT
        assert result.detail == "abstained on every page; gold states '2026-07-28'"
