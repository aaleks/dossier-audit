"""R7.50 — a declared field gold verifies and the run gave no record for is
scored as an abstention, and named `not answered`.

In every mode. Scored only by the records that exist, a left-out field got no
verdict at all, so a run that left out every field it was unsure of was never
wrong about one -- what R7.3 exists to prevent. Only a field the step declares:
a field the step was never asked for is not one it failed to answer.
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import FieldKind, GoldField, Verdict, score_document

GROUNDED = FieldCheck(FieldVerdict.VALID)
INCIDENT = "INC-4821"
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
CAUSE = "the renewed TLS certificate was never deployed to the load balancers"


def severity(document: str) -> FieldRecord:
    return FieldRecord(
        field="severity", value="major", source=Evidence(document=document, span="major")
    )


def verdicts(document, records, gold, kinds, parts=()):
    return {
        result.field: result
        for result in score_document(
            document=document,
            records=records,
            checks=[GROUNDED] * len(records),
            parts=parts,
            gold=gold,
            kinds=kinds,
        ).results
    }


class TestAFieldNeverAnsweredIsScoredAsAnAbstention:
    """R7.50 — leaving a field out is not a way to avoid being wrong about it."""

    def test_a_field_left_out_against_a_gold_value_is_incorrect(self):
        """Row 1 — the one where the run said nothing about the loss gold verified."""
        scored = verdicts(
            INCIDENT,
            [severity(INCIDENT)],
            {
                "severity": GoldField(value="major"),
                "loss_amount": GoldField(value=48200.00, currency="CHF"),
            },
            {"severity": FieldKind.ENUM, "loss_amount": FieldKind.AMOUNT},
        )

        assert scored["loss_amount"].verdict is Verdict.INCORRECT
        assert scored["loss_amount"].detail == "not answered; gold states 48200.0"

    def test_a_field_left_out_against_a_gold_null_is_correct(self):
        """Row 2 — the one where saying nothing agrees with a document that says nothing."""
        scored = verdicts(
            INCIDENT,
            [severity(INCIDENT)],
            {"severity": GoldField(value="major"), "root_cause": GoldField(value=None)},
            {"severity": FieldKind.ENUM, "root_cause": FieldKind.FREE_TEXT},
        )

        assert scored["root_cause"].verdict is Verdict.CORRECT

    def test_a_judged_field_no_page_gave_is_incorrect_without_a_judge(self):
        """Row 3 — the one where there is no candidate for the judge to read."""
        scored = verdicts(
            POSTMORTEM,
            [severity(POSTMORTEM)] * 3,
            {"severity": GoldField(value="major"), "root_cause": GoldField(value=CAUSE)},
            {"severity": FieldKind.ENUM, "root_cause": FieldKind.FREE_TEXT},
            parts=("page-001.png", "page-002.png", "page-003.png"),
        )

        assert scored["root_cause"].verdict is Verdict.INCORRECT
        assert scored["root_cause"].detail.startswith("not answered"), scored["root_cause"]

    def test_a_field_the_step_does_not_declare_is_not_scored(self):
        """Row 4, counter-example — the one where the step was never asked for it."""
        scored = verdicts(
            INCIDENT,
            [severity(INCIDENT)],
            {"severity": GoldField(value="major"), "root_cause": GoldField(value=CAUSE)},
            {"severity": FieldKind.ENUM},
        )

        assert set(scored) == {"severity"}

    def test_a_field_gold_did_not_verify_is_not_scored(self):
        """Row 5, counter-example — the one nobody verified an answer for (R7.3 row 4)."""
        scored = verdicts(
            INCIDENT,
            [severity(INCIDENT)],
            {"severity": GoldField(value="major")},
            {"severity": FieldKind.ENUM, "loss_amount": FieldKind.AMOUNT},
        )

        assert set(scored) == {"severity"}

    def test_a_document_the_step_failed_on_is_not_scored(self):
        """Row 6, counter-example — the one reported as failed, not as silent (R6.9)."""
        from datetime import date

        from dossier.application.eval import score_run
        from dossier.application.extract import DocumentResult
        from dossier.application.run import StepReport
        from dossier.domain.gold import GoldDocument

        report = StepReport(
            step="extract",
            results=(DocumentResult(document="INC-4822", error="invalid after retry"),),
        )
        gold = GoldDocument(
            document="INC-4822",
            verified_by="a.aleks",
            verified_at=date(2026, 9, 28),
            fields={"severity": {"value": "minor"}},
        )

        assert (
            score_run(
                report=report, gold={"INC-4822": gold}, kinds={"severity": FieldKind.ENUM}
            )
            == ()
        )
