"""R7.7 — accepted corrections are versioned, attributed and timestamped.

The gold set is the asset the whole system is measured against. An unattributed
edit to it is an unaudited change to the definition of correct — and every score
`dossier` has ever reported is a claim about agreement with it.

The failure this prevents is quiet and slow. Someone corrects a field to make a
run look right, nobody can later tell whether the model was wrong or the gold
was, and the number that gets quoted in a meeting is measuring agreement with an
edit nobody reviewed.

The rows below are the rule's example table, transcribed. Note what is *not*
here: nothing writes to `gold/`. This module decides what a correction must
carry, and the writing is a later slice with a human in it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from dossier.domain.gold import (
    AnonymousCorrection,
    Correction,
    GoldDocument,
    apply_correction,
)

REVIEWER = "a.muster"
VERIFIED_AT = date(2026, 8, 14)
LATER = date(2026, 9, 10)


def gold(**fields) -> GoldDocument:
    return GoldDocument(
        document="INC-4821",
        verified_by=REVIEWER,
        verified_at=VERIFIED_AT,
        fields=fields or {"severity": {"value": "minor"}},
    )


class TestOnlyAnAttributedCorrectionEnters:
    """R7.7 — a change to the definition of correct has a name on it."""

    def test_a_correction_records_who_made_it_and_when(self):
        """Example 1: the one where `severity` on `INC-4821` is corrected."""
        corrected = apply_correction(
            gold(),
            Correction(
                field="severity",
                value="major",
                verified_by="b.keller",
                verified_at=LATER,
            ),
        )

        assert corrected.fields["severity"]["value"] == "major"
        assert corrected.fields["severity"]["verified_by"] == "b.keller"
        assert corrected.fields["severity"]["verified_at"] == LATER.isoformat()

    def test_the_previous_value_is_recoverable(self):
        """Example 2: the one where the old answer is not simply overwritten.

        The file is committed to git, so history is the primary record -- but a
        correction that silently replaced a value would make a `git log -p` show
        *that* something changed without showing what it displaced in the same
        place a reviewer is reading. The superseded value travels with the field.
        """
        corrected = apply_correction(
            gold(severity={"value": "minor"}),
            Correction(
                field="severity", value="major", verified_by="b.keller", verified_at=LATER
            ),
        )

        assert corrected.fields["severity"]["superseded"] == "minor"

    def test_a_correction_with_no_reviewer_is_refused(self):
        """Example 3: the one with no name on it.

        There is no anonymous path into the gold set. An automated correction
        would be indistinguishable from a reviewed one the moment it landed, and
        the whole value of the gold set is that a person stood behind it.
        """
        for missing in ("", "   "):
            with pytest.raises(AnonymousCorrection):
                apply_correction(
                    gold(),
                    Correction(
                        field="severity",
                        value="major",
                        verified_by=missing,
                        verified_at=LATER,
                    ),
                )

    def test_a_models_agreement_changes_nothing(self):
        """Counter-example (row 4): the one where a run agrees with gold.

        Only a reviewer's decision enters the gold set, never a model's. This
        module has no way to accept one -- a `Correction` carries a reviewer and
        a date, and there is nowhere to put a run id -- which is the strongest
        form the guarantee takes.
        """
        assert "run_id" not in Correction.model_fields
        assert "confidence" not in Correction.model_fields
        assert set(Correction.model_fields) == {
            "field",
            "value",
            "verified_by",
            "verified_at",
            "reason",
        }

    def test_correcting_a_field_gold_did_not_have_adds_it(self):
        """The one where review grows the gold set rather than only fixing it.

        "Reviewing is how the gold set grows. There is no separate labelling
        exercise." A field nobody had verified becomes one that someone has, and
        it carries the same attribution as any other correction.
        """
        corrected = apply_correction(
            gold(severity={"value": "minor"}),
            Correction(
                field="loss_amount",
                value=48200.00,
                verified_by="b.keller",
                verified_at=LATER,
            ),
        )

        assert corrected.fields["loss_amount"]["value"] == 48200.00
        assert corrected.fields["loss_amount"]["verified_by"] == "b.keller"
        assert "superseded" not in corrected.fields["loss_amount"], (
            "there was nothing to supersede"
        )

    def test_a_correction_to_null_is_a_correction(self):
        """The one where the right answer is that the document does not say.

        `root_cause: null` with a reason is a conforming gold answer (R7.3), so a
        reviewer must be able to correct *to* it. A guard that treated a null
        value as a missing one would make "the model invented this" the one
        finding review could not record.
        """
        corrected = apply_correction(
            gold(root_cause={"value": "cable fault"}),
            Correction(
                field="root_cause",
                value=None,
                reason="not stated in document",
                verified_by="b.keller",
                verified_at=LATER,
            ),
        )

        assert corrected.fields["root_cause"]["value"] is None
        assert corrected.fields["root_cause"]["reason"] == "not stated in document"
        assert corrected.fields["root_cause"]["superseded"] == "cable fault"

    def test_the_original_document_is_not_mutated(self):
        """The one where a correction returns a new document.

        A gold set is read by a scorer and written by a reviewer, and an
        in-place edit would let a scoring run see a half-applied correction.
        Frozen models make it structural rather than a convention.
        """
        before = gold(severity={"value": "minor"})

        apply_correction(
            before,
            Correction(
                field="severity", value="major", verified_by="b.keller", verified_at=LATER
            ),
        )

        assert before.fields["severity"] == {"value": "minor"}

    def test_a_naive_or_future_dated_correction_is_refused(self):
        """The one where the timestamp cannot be trusted.

        `verified_at` is the audit trail's date. A future date is a clock
        problem or a typo, and either way it sorts wrongly against every other
        correction forever.
        """
        with pytest.raises(ValueError):
            apply_correction(
                gold(),
                Correction(
                    field="severity",
                    value="major",
                    verified_by="b.keller",
                    verified_at=date(2099, 1, 1),
                ),
                today=datetime(2026, 9, 10, tzinfo=UTC).date(),
            )
