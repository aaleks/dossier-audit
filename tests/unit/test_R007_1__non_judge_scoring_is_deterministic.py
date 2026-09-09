"""R7.1 — scoring is deterministic for every non-judge field type.

The same output and gold set always produce the same score.

Determinism here is not an optimisation, it is what makes a score an argument.
"94.1%" is only worth quoting if re-running it tomorrow, on another machine,
produces 94.1% again -- otherwise a regression and a rounding difference look
identical, and every comparison between two runs becomes a matter of opinion.

Normalisation is the whole of the interesting part. `48'200.00 CHF` and
`48200.00` are the same amount written by two people; `28.07.2026` and
`2026-07-28` are the same day. A scorer that called those wrong would report a
model as failing at something it got right, which is worse than no score at all.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import GoldField, Verdict, score_field

GROUNDED = FieldCheck(FieldVerdict.VALID)
SPAN = Evidence(document="INC-4821", span="total exposure CHF 48'200")


def record(field: str, value, currency: str | None = None) -> FieldRecord:
    return FieldRecord(field=field, value=value, currency=currency, source=SPAN)


def scored(produced: FieldRecord, gold: GoldField) -> Verdict:
    return score_field(record=produced, gold=gold, check=GROUNDED).verdict


class TestNonJudgeScoring:
    """R7.1 — an exact answer, arrived at the same way every time."""

    def test_an_amount_matching_gold_is_correct(self):
        """Example 1: the one where the two are already identical."""
        assert scored(
            record("loss_amount", 48200.00, "CHF"),
            GoldField(value=48200.00, currency="CHF"),
        ) is Verdict.CORRECT

    def test_a_formatted_amount_is_normalised_before_comparison(self):
        """Example 2: the one written the Swiss way.

        `48'200.00 CHF` is what a person types and what a model reads back off a
        page. Comparing the strings would mark it wrong; comparing the amounts
        marks it right, which is the only defensible answer.
        """
        assert scored(
            record("loss_amount", "48'200.00 CHF", "CHF"),
            GoldField(value=48200.00, currency="CHF"),
        ) is Verdict.CORRECT

    def test_a_date_in_another_format_is_normalised(self):
        """Example 3: the one where `28.07.2026` is `2026-07-28`."""
        assert scored(
            record("resolution_date", "28.07.2026"),
            GoldField(value="2026-07-28"),
        ) is Verdict.CORRECT

    def test_a_free_text_field_is_not_scored_here(self):
        """Counter-example (row 4): the one that belongs to a judge.

        `root_cause` is free text. This scorer must decline it rather than reach
        for string equality, which would quietly turn an `evaluated` rule into a
        deterministic one nobody agreed to (R7.11).
        """
        result = score_field(
            record=record("root_cause", "a certificate expired"),
            gold=GoldField(value="the TLS certificate expired", judged=True),
            check=GROUNDED,
        )

        assert result.verdict is Verdict.NEEDS_JUDGE
        assert result.field == "root_cause"

    @pytest.mark.parametrize(
        ("produced", "gold"),
        [
            (48200.0, 48200.00),
            ("48200", 48200.00),
            ("48,200.00", 48200.00),
            ("CHF 48'200.00", 48200.00),
            (" 48200.00 ", 48200.00),
        ],
    )
    def test_amounts_that_mean_the_same_number_all_score_correct(self, produced, gold):
        """The one where the same amount is written five ways.

        Each is a real form: a float, a bare string, an English thousands
        separator, a Swiss one with the currency in front, and one with stray
        whitespace. None of them is a different answer.
        """
        assert scored(
            record("loss_amount", produced, "CHF"), GoldField(value=gold, currency="CHF")
        ) is Verdict.CORRECT

    def test_a_different_amount_is_incorrect(self):
        """The one that stops normalisation swallowing everything.

        A scorer generous enough to make every row above pass could be generous
        enough to pass this too, and then the number it reports means nothing.
        """
        assert scored(
            record("loss_amount", 48250.00, "CHF"), GoldField(value=48200.00, currency="CHF")
        ) is Verdict.INCORRECT

    def test_a_different_currency_is_incorrect(self):
        """The one where the number matches and the money does not.

        CHF 48'200 and EUR 48'200 are different losses. Comparing only the
        magnitude would report a currency error as a correct answer.
        """
        assert scored(
            record("loss_amount", 48200.00, "EUR"), GoldField(value=48200.00, currency="CHF")
        ) is Verdict.INCORRECT

    def test_an_enum_is_compared_after_case_folding(self):
        """The one where `Major` and `major` are the same severity.

        An enum's values are a closed set agreed in the schema; which case the
        model happened to echo them back in is not information.
        """
        assert scored(
            record("severity", "Major"), GoldField(value="major")
        ) is Verdict.CORRECT

    def test_scoring_the_same_pair_twice_gives_the_same_verdict(self):
        """The rule's own sentence, asserted directly.

        Cheap, and the one assertion that would catch a scorer reaching for a
        clock, a random tiebreak or an iteration order.
        """
        produced = record("loss_amount", "48'200.00 CHF", "CHF")
        gold = GoldField(value=48200.00, currency="CHF")

        first = score_field(record=produced, gold=gold, check=GROUNDED)
        second = score_field(record=produced, gold=gold, check=GROUNDED)

        assert first == second
