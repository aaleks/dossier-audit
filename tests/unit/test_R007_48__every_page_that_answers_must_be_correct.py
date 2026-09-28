"""R7.48 — a field is correct only when every page that gave it a value is
correct, and the detail names each page that was not.

Each page's value is scored as a `per_file` step's record is: grounded (R7.4),
then compared with gold by its kind. Each page is held to gold and never to the
other pages, so two pages spelling one answer differently agree. A page is named
as the part it came from (R8.11). The values are `_fixtures.md`'s "`INC-4830`
page by page".
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import FieldKind, GoldField, Verdict, score_document

POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
GROUNDED = FieldCheck(FieldVerdict.VALID)
UNGROUNDED = FieldCheck(FieldVerdict.UNGROUNDED, "span not found")
KINDS = {
    "severity": FieldKind.ENUM,
    "resolution_date": FieldKind.DATE,
    "loss_amount": FieldKind.AMOUNT,
    "affected_systems": FieldKind.LIST,
}


def answered(field: str, value, **extra) -> FieldRecord:
    return FieldRecord(
        field=field, value=value, source=Evidence(document=POSTMORTEM, span=str(value)), **extra
    )


def verdict_of(pages, gold: dict[str, GoldField]):
    """`pages` is `(part, record, check)` in part order, as a run joins them."""
    (result,) = score_document(
        document=POSTMORTEM,
        records=[record for _, record, _ in pages],
        checks=[check for _, _, check in pages],
        parts=[part for part, _, _ in pages],
        gold=gold,
        kinds=KINDS,
    ).results
    return result


class TestEveryPageThatAnswersMustBeCorrect:
    """R7.48 — a right page does not vouch for a wrong one, and the wrong one is named."""

    def test_a_page_giving_another_date_makes_the_field_incorrect(self):
        """Row 1 — the one where page 2 took the review's date for the resolution."""
        result = verdict_of(
            [
                ("page-001.png", answered("resolution_date", "2026-07-28"), GROUNDED),
                ("page-002.png", answered("resolution_date", "2026-07-30"), GROUNDED),
            ],
            {"resolution_date": GoldField(value="2026-07-28")},
        )

        assert result.verdict is Verdict.INCORRECT
        assert result.detail == "page-002.png: '2026-07-30' does not match '2026-07-28'"

    def test_a_page_with_no_evidence_makes_the_field_incorrect(self):
        """Row 2 — the one where the right value on page 1 does not vouch for page 3."""
        amount = {"currency": "CHF"}
        result = verdict_of(
            [
                ("page-001.png", answered("loss_amount", "48200.00", **amount), GROUNDED),
                ("page-003.png", answered("loss_amount", "48200.00", **amount), UNGROUNDED),
            ],
            {"loss_amount": GoldField(value=48200.00, currency="CHF")},
        )

        assert result.verdict is Verdict.INCORRECT
        assert result.detail.startswith("page-003.png: ungrounded"), result.detail
        assert "page-001.png" not in result.detail

    def test_pages_spelling_one_answer_differently_agree(self):
        """Row 3 — the one where `Critical` on page 3 is the same enum value."""
        result = verdict_of(
            [
                ("page-001.png", answered("severity", "critical"), GROUNDED),
                ("page-002.png", answered("severity", "critical"), GROUNDED),
                ("page-003.png", answered("severity", "Critical"), GROUNDED),
            ],
            {"severity": GoldField(value="critical")},
        )

        assert result.verdict is Verdict.CORRECT

    def test_a_lists_items_on_different_pages_are_not_a_disagreement(self):
        """Row 4, counter-example — the one where two pages name two systems of one list."""
        result = verdict_of(
            [
                ("page-001.png", answered("affected_systems", "payments-api"), GROUNDED),
                ("page-003.png", answered("affected_systems", "ledger-batch"), GROUNDED),
            ],
            {"affected_systems": GoldField(value=["payments-api", "ledger-batch"])},
        )

        assert result.verdict is Verdict.CORRECT


class TestTheRunHandsThePagesToTheScorer:
    """R7.48, the application's half: a joined document carries the page of each record."""

    def test_the_page_a_joined_document_answered_on_reaches_the_miss(self):
        """Row 1, through `score_run` — the one where the page is not lost in the join."""
        from datetime import date

        from dossier.application.eval import score_run
        from dossier.application.extract import DocumentResult
        from dossier.application.run import StepReport
        from dossier.domain.gold import GoldDocument

        records = (
            answered("resolution_date", "2026-07-28"),
            answered("resolution_date", "2026-07-30"),
        )
        report = StepReport(
            step="extract",
            results=(
                DocumentResult(
                    document=POSTMORTEM,
                    records=records,
                    checks=(GROUNDED, GROUNDED),
                    parts=("page-001.png", "page-002.png"),
                ),
            ),
        )
        gold = GoldDocument(
            document=POSTMORTEM,
            verified_by="a.aleks",
            verified_at=date(2026, 9, 28),
            fields={"resolution_date": {"value": "2026-07-28"}},
        )

        (score,) = score_run(report=report, gold={POSTMORTEM: gold}, kinds=KINDS)

        (result,) = score.results
        assert result.detail == "page-002.png: '2026-07-30' does not match '2026-07-28'"
