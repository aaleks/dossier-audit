"""R7.36 — a `boolean` field is correct when the run and gold hold the same
truth value.

`true` and `false`, or the strings `"true"` and `"false"` in any case: whether
a model quoted a JSON value is not information, as the case of an enum is not.
Anything else is not a well-formed boolean, and is reported as unreadable
rather than as a mismatch. `1` is a number and `yes` is a word, and reading
either would start a vocabulary nobody agreed to.

The one worth watching is row 2. `False` is falsy in Python, and a scorer that
tested a value's truth rather than its presence would read "does not renew" as
"did not say" -- exactly the confusion R7.3 exists to keep apart.

Values are `_fixtures.md`'s "Fields on the contracts".
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import FieldKind, GoldField, Verdict, score_field

GROUNDED = FieldCheck(FieldVerdict.VALID)
RENEWS = Evidence(
    document="ACME-2024", span="renews automatically for successive one-year terms"
)
DOES_NOT_RENEW = Evidence(
    document="GLOBEX-2023", span="This Agreement shall not renew automatically"
)


def scored(value, gold, source: Evidence = RENEWS):
    return score_field(
        record=FieldRecord(field="auto_renew", value=value, source=source),
        gold=GoldField(value=gold),
        check=GROUNDED,
        kind=FieldKind.BOOLEAN,
    )


class TestABooleanIsScoredByItsTruthValue:
    """R7.36 — the same truth value, and nothing else read as one."""

    def test_true_against_true_is_correct(self):
        """Row 1 — the one where the contract renews."""
        assert scored(True, True).verdict is Verdict.CORRECT

    def test_false_is_an_answer_and_not_an_abstention(self):
        """Row 2 — the one where false is an answer."""
        score = scored(False, False, source=DOES_NOT_RENEW)

        assert score.verdict is Verdict.CORRECT
        assert "abstain" not in (score.detail or "")

    def test_a_quoted_true_is_true(self):
        """Row 3 — the one where the model quoted it."""
        assert scored("True", True).verdict is Verdict.CORRECT

    def test_false_against_true_is_a_mismatch(self):
        """Row 4 — the one that disagrees."""
        score = scored(False, True)

        assert score.verdict is Verdict.INCORRECT
        assert "does not match" in score.detail

    def test_one_is_not_true(self):
        """Row 5, counter-example — the one where 1 is a number."""
        score = scored(1, True)

        assert score.verdict is Verdict.INCORRECT
        assert "not a well-formed boolean" in score.detail

    def test_yes_is_a_word(self):
        """Row 6, counter-example — the one where yes is not in the vocabulary."""
        score = scored("yes", True)

        assert score.verdict is Verdict.INCORRECT
        assert "not a well-formed boolean" in score.detail

    def test_a_contract_that_says_nothing_is_not_false(self):
        """Row 7, counter-example — the one where silence is not false (R7.3)."""
        score = scored(False, None, source=DOES_NOT_RENEW)

        assert score.verdict is Verdict.INCORRECT
        assert "abstain" in score.detail
