"""R7.4 — an ungrounded field is scored incorrect even when its value matches gold.

The value being right by accident is not evidence, and accepting it would make
the grounding check decorative.

This is the rule that decides what `dossier` is measuring. A tool that scored a
correct-looking value as correct would be measuring whether a model can produce
plausible numbers -- which it can, reliably, including for documents that say
nothing of the sort. Requiring the span makes the score a claim about *evidence*,
which is the only claim an audit can defend.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import FieldKind, GoldField, Verdict, score_field

SPAN = Evidence(document="INC-4821", span="total exposure CHF 48'200")
GROUNDED = FieldCheck(FieldVerdict.VALID)
UNGROUNDED = FieldCheck(
    FieldVerdict.UNGROUNDED, "span not found in the converted text of INC-4821"
)
ABSTAINED = FieldCheck(FieldVerdict.ABSTAINED)

GOLD = GoldField(value=48200.00, currency="CHF")


def loss(value=48200.00) -> FieldRecord:
    return FieldRecord(field="loss_amount", value=value, currency="CHF", source=SPAN)


class TestEvidenceIsRequired:
    """R7.4 — right for the wrong reason is not right."""

    def test_an_ungrounded_field_is_incorrect_even_matching_gold(self):
        """Example 1: the one where the number is right and nothing shows it.

        `48200.00` is exactly what gold says. The span cannot be found in the
        document, so the model produced the right number from somewhere other
        than the evidence -- and this rule says that does not count.
        """
        result = score_field(
            record=loss(), gold=GOLD, check=UNGROUNDED, kind=FieldKind.AMOUNT
        )

        assert result.verdict is Verdict.INCORRECT

    def test_it_is_reported_as_ungrounded_not_as_a_mismatch(self):
        """Example 2: the one where the reason has to survive into review.

        Both are incorrect, and they need completely different work: a mismatch
        means the model read the wrong thing, ungrounded means it read nothing.
        A `review.jsonl` that called both "incorrect" would send someone hunting
        for a disagreement that does not exist.
        """
        result = score_field(
            record=loss(), gold=GOLD, check=UNGROUNDED, kind=FieldKind.AMOUNT
        )
        mismatch = score_field(
            record=loss(48250.00), gold=GOLD, check=GROUNDED, kind=FieldKind.AMOUNT
        )

        assert "ungrounded" in (result.detail or "")
        assert "ungrounded" not in (mismatch.detail or "")
        assert result.detail != mismatch.detail

    def test_a_grounded_matching_field_is_correct(self):
        """Example 3: the one where the check is not simply always failing.

        Same value, same gold, locatable span. Without this row the rule is
        satisfied by a scorer that marks everything incorrect.
        """
        result = score_field(
            record=loss(), gold=GOLD, check=GROUNDED, kind=FieldKind.AMOUNT
        )

        assert result.verdict is Verdict.CORRECT

    def test_an_abstention_is_not_ungrounded(self):
        """Counter-example (row 4): the one where there is no span to find.

        An abstaining field carries no span by construction, so it cannot be
        ungrounded. It is scored against gold by R7.3 instead -- and a scorer
        that treated "no span" as "ungrounded" would make every correct
        abstention incorrect, which is exactly backwards.
        """
        abstains = FieldRecord(
            field="root_cause", value=None, reason="not stated in document"
        )

        result = score_field(
            record=abstains,
            gold=GoldField(value=None),
            check=ABSTAINED,
            kind=FieldKind.FREE_TEXT,
        )

        assert result.verdict is Verdict.CORRECT
        assert "ungrounded" not in (result.detail or "")

    def test_grounding_is_checked_before_the_value_is_compared(self):
        """The one that pins the order of the two checks.

        An ungrounded field whose value *disagrees* with gold is still reported
        as ungrounded, not as a mismatch. The missing evidence is the finding;
        the value disagreeing is a detail about a number nobody can trace.
        """
        result = score_field(
            record=loss(48250.00), gold=GOLD, check=UNGROUNDED, kind=FieldKind.AMOUNT
        )

        assert result.verdict is Verdict.INCORRECT
        assert "ungrounded" in (result.detail or "")
