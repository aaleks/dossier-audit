"""R7.17 — a free-text field with a value in gold and a grounded value in the run
is scored by the judge, asked the calibrated question of the run's answer.

The decision half. Asking the judge is the application's (`judged_cached`,
R7.18) and what a person sees is the acceptance test's; what a verdict *does*
to a document's score, and how a field's total counts it, is pure and lives
here. Rows 1, 2 and 3 at the decision; rows 4 to 7 are the command's.
"""

from __future__ import annotations

from dossier.domain.scoring import DocumentScore, FieldScore, Verdict, per_field, with_judged

DEFERRED = FieldScore("root_cause", Verdict.NEEDS_JUDGE, "free text; scored by a judge")
EVIDENCE = "the document names the freeze only as a contributing factor"


class TestAFreeTextFieldIsScoredByTheJudge:
    """R7.17 — the judge decides only what is left, and the total says it did."""

    def test_a_supported_verdict_makes_the_field_correct(self):
        """Example 1: the one where the judge found the candidate supported."""
        score = DocumentScore("INC-4830", results=(DEFERRED,))

        judged = with_judged(score, {"root_cause": (True, "the certificate paragraph")})

        assert judged.results == (
            FieldScore("root_cause", Verdict.CORRECT, "the certificate paragraph", judged=True),
        )
        assert judged.scored == judged.results, "a judged verdict counts"

    def test_an_unsupported_verdict_makes_the_field_incorrect_with_the_evidence(self):
        """Example 2: the one where the judge found the planted claim unsupported.

        The evidence is the reason a person reads, as an ungrounded span is for
        R7.4: incorrect, and distinguishable from a value that merely disagreed.
        """
        score = DocumentScore("INC-4830", results=(DEFERRED,))

        judged = with_judged(score, {"root_cause": (False, EVIDENCE)})

        assert judged.results[0].verdict is Verdict.INCORRECT
        assert judged.results[0].detail == EVIDENCE
        assert judged.results[0].judged is True

    def test_the_total_counts_how_many_verdicts_were_judged(self):
        """Example 3: the one where one of five verdicts came from the judge.

        Three of five correct, and the total says one of them was judged: the
        count is carried, never implied, so the report can print it.
        """
        abstained = FieldScore("root_cause", Verdict.CORRECT, "abstained, as gold does")
        guessed = FieldScore("root_cause", Verdict.INCORRECT, "gold abstains")
        scores = (
            DocumentScore("INC-4821", results=(abstained,)),
            DocumentScore("INC-4822", results=(guessed,)),
            DocumentScore("INC-4901", results=(abstained,)),
            DocumentScore("INC-5455", results=(guessed,)),
            with_judged(
                DocumentScore("INC-4830", results=(DEFERRED,)),
                {"root_cause": (True, "stated")},
            ),
        )

        (total,) = per_field(scores, declared=["root_cause"])

        assert (total.correct, total.scored, total.judged) == (3, 5, 1)
        assert total.percentage == 60.0

    def test_a_field_the_judge_was_not_asked_about_stays_unscored(self):
        """Counter-example (row 6's shape): the one with no verdict for it.

        A withheld field is never judged, so its deferred result stays out of
        the total rather than being counted as anything.
        """
        score = DocumentScore("INC-4830", results=(DEFERRED,))

        untouched = with_judged(score, {})

        assert untouched.results == (DEFERRED,)
        assert untouched.scored == ()
