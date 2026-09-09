"""R7.3 — a gold null is correct when the run abstains and incorrect when it
supplies a value.

Abstention has to be scorable, or the system learns that guessing is free.

That sentence is the whole rule and it cuts both ways. If abstaining on a field
the document genuinely does not state scored as *wrong*, the only way to score
well would be to invent something — which is precisely the behaviour an audit
tool exists to catch. And if supplying a value where gold says `null` scored as
*right*, the abstention would be worthless: a model could answer everything and
lose nothing.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import GoldField, Verdict, score_document, score_field

ABSTAINED = FieldCheck(FieldVerdict.ABSTAINED)
GROUNDED = FieldCheck(FieldVerdict.VALID)
SPAN = Evidence(document="INC-4821", span="the cable had failed")


def abstention(field: str, reason: str = "not stated in document") -> FieldRecord:
    return FieldRecord(field=field, value=None, reason=reason)


def answered(field: str, value: str) -> FieldRecord:
    return FieldRecord(field=field, value=value, source=SPAN)


class TestAbstentionIsScored:
    """R7.3 — `null` is an answer, and it can be right or wrong."""

    def test_abstaining_where_gold_is_null_is_correct(self):
        """Example 1: the one where the document really does not say.

        `root_cause` is the fixtures' abstention example: the incident report
        never states a cause, and saying so is the correct answer.
        """
        result = score_field(
            record=abstention("root_cause"), gold=GoldField(value=None), check=ABSTAINED
        )

        assert result.verdict is Verdict.CORRECT

    def test_answering_where_gold_is_null_is_incorrect(self):
        """Example 2: the one where the model supplied something plausible.

        A grounded span does not save it. The span shows the model read *some*
        sentence; gold says the document does not state a root cause, so what it
        read is not one. This is the row that makes guessing cost something.
        """
        result = score_field(
            record=answered("root_cause", "cable fault"),
            gold=GoldField(value=None),
            check=GROUNDED,
        )

        assert result.verdict is Verdict.INCORRECT
        assert "abstain" in (result.detail or "").lower()

    def test_abstaining_where_gold_has_a_value_is_incorrect(self):
        """Example 3: the one where the answer was there to be found.

        The mirror of the row above, and the reason abstention cannot simply be
        made free: a model that abstained on everything would otherwise score
        perfectly on every field a document does state.
        """
        result = score_field(
            record=abstention("root_cause"),
            gold=GoldField(value="cable fault"),
            check=ABSTAINED,
        )

        assert result.verdict is Verdict.INCORRECT

    def test_a_field_absent_from_gold_is_not_scored_at_all(self):
        """Counter-example (row 4): the one where nobody verified anything.

        Absent is not `null`. `null` is a human saying "the document does not
        state this"; absent is a human not having looked. Scoring it either way
        would invent a verdict nobody stands behind.
        """
        report = score_document(
            document="INC-4821",
            records=[answered("severity", "major"), answered("affected_systems", "api")],
            checks={"severity": GROUNDED, "affected_systems": GROUNDED},
            gold={"severity": GoldField(value="major")},
        )

        assert [result.field for result in report.results] == ["severity"]
        assert "affected_systems" in report.not_in_gold

    def test_an_abstention_without_a_reason_is_not_correct(self):
        """The one where a bare null is not an abstention.

        R6.5 makes a reason part of what abstention *is*: without one, a null is
        indistinguishable from a field the model forgot. Scoring it correct
        against a gold null would reward exactly that forgetting.
        """
        result = score_field(
            record=FieldRecord(field="root_cause", value=None),
            gold=GoldField(value=None),
            check=FieldCheck(FieldVerdict.INVALID, "value is null with no reason"),
        )

        assert result.verdict is Verdict.INCORRECT

    def test_gold_null_and_gold_absent_are_different_states(self):
        """The distinction row 4 rests on, asserted on its own.

        Two fields, one verified as "not stated" and one never looked at. One is
        scored and one is not, and a gold format that could not tell them apart
        would make R7.3 unimplementable.
        """
        report = score_document(
            document="INC-4821",
            records=[abstention("root_cause"), abstention("owner")],
            checks={"root_cause": ABSTAINED, "owner": ABSTAINED},
            gold={"root_cause": GoldField(value=None)},
        )

        assert [(r.field, r.verdict) for r in report.results] == [
            ("root_cause", Verdict.CORRECT)
        ]
        assert report.not_in_gold == ("owner",)
