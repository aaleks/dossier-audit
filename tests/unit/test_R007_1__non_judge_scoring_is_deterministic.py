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
from dossier.domain.scoring import FieldKind, GoldField, Verdict, score_field

GROUNDED = FieldCheck(FieldVerdict.VALID)
SPAN = Evidence(document="INC-4821", span="total exposure CHF 48'200")


def record(field: str, value, currency: str | None = None) -> FieldRecord:
    return FieldRecord(field=field, value=value, currency=currency, source=SPAN)


def scored(produced: FieldRecord, gold: GoldField, kind=FieldKind.AMOUNT) -> Verdict:
    return score_field(record=produced, gold=gold, check=GROUNDED, kind=kind).verdict


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
            kind=FieldKind.DATE,
        ) is Verdict.CORRECT

    def test_a_free_text_field_is_not_scored_here(self):
        """Counter-example (row 4): the one that belongs to a judge.

        `root_cause` is free text. This scorer must decline it rather than reach
        for string equality, which would quietly turn an `evaluated` rule into a
        deterministic one nobody agreed to (R7.11).
        """
        result = score_field(
            record=record("root_cause", "a certificate expired"),
            gold=GoldField(value="the TLS certificate expired"),
            check=GROUNDED,
            kind=FieldKind.FREE_TEXT,
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
            record("severity", "Major"), GoldField(value="major"), kind=FieldKind.ENUM
        ) is Verdict.CORRECT

    def test_scoring_the_same_pair_twice_gives_the_same_verdict(self):
        """The rule's own sentence, asserted directly.

        Cheap, and the one assertion that would catch a scorer reaching for a
        clock, a random tiebreak or an iteration order.
        """
        produced = record("loss_amount", "48'200.00 CHF", "CHF")
        gold = GoldField(value=48200.00, currency="CHF")

        first = score_field(record=produced, gold=gold, check=GROUNDED, kind=FieldKind.AMOUNT)
        second = score_field(record=produced, gold=gold, check=GROUNDED, kind=FieldKind.AMOUNT)

        assert first == second


class TestAValueThatIsNotWellFormedIsNotAMismatch:
    """R7.1 — an unreadable value and a disagreeing value are different findings.

    Both were found by `/quality`. The scorer used to sniff each value's type,
    which made the verdict depend on what the model returned rather than on what
    the field is; and `_as_date` guessed day-first on ambiguous input while its
    own docstring claimed it refused to.
    """

    def test_an_ambiguous_date_is_refused_rather_than_guessed(self):
        """The one where `07/08/2026` could be either month.

        7 August or 8 July, depending on the reader's country. Resolving it
        silently would make the scorer quietly wrong for half of every year --
        and the wrongness would look like a model error, not a scorer error.
        """
        result = score_field(
            record=record("resolution_date", "07/08/2026"),
            gold=GoldField(value="2026-08-07"),
            check=GROUNDED,
            kind=FieldKind.DATE,
        )

        assert result.verdict is Verdict.INCORRECT
        assert "well-formed" in (result.detail or "")

    def test_an_unambiguous_day_first_date_is_still_read(self):
        """The counter-example to the row above: no month is 28.

        Refusing everything with slashes would be safe and useless. The rule is
        ambiguity, not format.
        """
        assert scored(
            record("resolution_date", "28.07.2026"),
            GoldField(value="2026-07-28"),
            kind=FieldKind.DATE,
        ) is Verdict.CORRECT

    def test_an_unreadable_value_is_reported_as_unreadable(self):
        """The one where a mismatch and a malformed value need different work.

        `not a date at all` is not a disagreement with gold; it is a field that
        cannot be compared. Reporting it as a mismatch would send someone hunting
        for a discrepancy that does not exist.
        """
        result = score_field(
            record=record("resolution_date", "not a date at all"),
            gold=GoldField(value="2026-07-28"),
            check=GROUNDED,
            kind=FieldKind.DATE,
        )
        mismatch = score_field(
            record=record("resolution_date", "2026-07-29"),
            gold=GoldField(value="2026-07-28"),
            check=GROUNDED,
            kind=FieldKind.DATE,
        )

        assert result.verdict is mismatch.verdict is Verdict.INCORRECT
        assert result.detail != mismatch.detail

    def test_the_declared_kind_decides_and_not_the_value(self):
        """The one that makes R7.1's determinism claim structural.

        `"48200"` against `48200.0` is correct as an amount and incorrect as an
        enum, because they are different questions. A scorer that sniffed the
        value would answer whichever the model's formatting suggested.
        """
        as_amount = scored(
            record("loss_amount", "48200"), GoldField(value=48200.0), kind=FieldKind.AMOUNT
        )
        as_enum = scored(
            record("severity", "48200"), GoldField(value=48200.0), kind=FieldKind.ENUM
        )

        assert as_amount is Verdict.CORRECT
        assert as_enum is Verdict.INCORRECT


class TestAmountSeparatorsAreReadTheWayTheyAreWritten:
    """R7.1 — an amount is normalised, not guessed at.

    Two findings met here. `/quality` reported that `48,20` normalised to
    `4820.0`: a hundredfold error, produced confidently, against gold nobody
    would think to re-check. And fixing it surfaced that the separator character
    class had been mojibake since it was written -- it held `â`, `€`, `™` and `Â`
    where `’` and a non-breaking space were meant, so the two separators a
    European document actually uses were never stripped at all.
    """

    def test_a_comma_grouping_threes_is_a_thousands_separator(self):
        """The one where the comma is unambiguous."""
        assert scored(
            record("loss_amount", "48,200.00", "CHF"),
            GoldField(value=48200.00, currency="CHF"),
        ) is Verdict.CORRECT

    def test_a_comma_not_grouping_threes_is_refused(self):
        """The one that was a hundredfold error.

        `48,20` is 48.20 to most of Europe and 4820 to a naive stripper, and
        nothing in the value says which was meant. Refused, so it reports as
        unreadable rather than as a wrong number that looks right.
        """
        result = score_field(
            record=record("loss_amount", "48,20", "CHF"),
            gold=GoldField(value=48.20, currency="CHF"),
            check=GROUNDED,
            kind=FieldKind.AMOUNT,
        )

        assert result.verdict is Verdict.INCORRECT
        assert "well-formed" in (result.detail or "")

    def test_a_curly_apostrophe_is_a_thousands_separator(self):
        """The one the mojibake broke.

        `48’200` with a typographic apostrophe is what a word processor produces
        from a Swiss keyboard, and it is the form `specs/_fixtures.md` uses for
        the worked example. It was not being stripped.
        """
        assert scored(
            record("loss_amount", "48\u2019200.00", "CHF"),
            GoldField(value=48200.00, currency="CHF"),
        ) is Verdict.CORRECT

    def test_a_non_breaking_space_is_a_thousands_separator(self):
        """The other half of the same corruption.

        A non-breaking space is the SI thousands separator and what a PDF
        extractor commonly emits.
        """
        assert scored(
            record("loss_amount", "48\u00a0200.00", "CHF"),
            GoldField(value=48200.00, currency="CHF"),
        ) is Verdict.CORRECT
