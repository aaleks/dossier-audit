"""Scoring a run's output against verified answers (spec 007).

Pure decisions, and deliberately the largest pure module in the project. A score
is an argument -- "this change made `loss_amount` worse" -- and an argument is
only worth having if re-running it tomorrow on another machine produces the same
number. So there is no clock here, no filesystem, no model, and nothing that
could vary: `score_field` takes what it needs and answers (R7.1, R7.10).

Three verdicts and one non-verdict, because the spec draws three lines and
collapsing any of them loses something:

- a field is `CORRECT` or `INCORRECT` against gold;
- a free-text field is `NEEDS_JUDGE` and is not scored here at all, because
  deciding it with string equality would turn an `evaluated` rule into a
  deterministic one nobody agreed to (R7.11);
- a field absent from gold is not scored, and does not appear in the results at
  all. Absent is not `null`: `null` is a human saying the document does not state
  it, absent is a human not having looked (R7.3 example 4).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.pipeline import reads_reference
from dossier.domain.resolution import ResolvedPlan
from dossier.domain.schemas import FieldRecord

# Unambiguous thousands separators: a Swiss apostrophe, or whitespace. Neither is
# a decimal point in any convention, so `48'200.00` and `48 200.00` and
# `48200.00` are one amount written three ways (R7.1 example 2).
_THOUSANDS = re.compile(r"[\s'’ ]")

# A comma is a thousands separator only where it groups exactly three digits all
# the way down -- `48,200` and `1,234,567`. `48,20` and `1,5` are a decimal comma
# in most of Europe and malformed elsewhere, and stripping them read `48,20` as
# 4820.00: a hundredfold error, reported confidently, against gold nobody would
# think to re-check. Refused for the same reason `07/08/2026` is.
_COMMA_GROUPS = re.compile(r"^\d{1,3}(,\d{3})+$")

# A currency written alongside the value rather than in its own field.
_CURRENCY_PREFIX = re.compile(r"^([A-Z]{3})\s*")
_CURRENCY_SUFFIX = re.compile(r"\s*([A-Z]{3})$")

# `28.07.2026`, `28/07/2026`, `2026-07-28`. Deliberately not a general date
# parser: an ambiguous form like `07/08/2026` is not resolved by guessing a
# locale, and a scorer that guessed would be wrong silently for half a year.
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_LITTLE_ENDIAN = re.compile(r"^(\d{2})[./](\d{2})[./](\d{4})$")


class FieldKind(Enum):
    """What kind of answer a field holds, which is what picks its scorer.

    The names and the groupings are spec 007's Scorers table. The kind comes from
    the field's declared type -- "scorers are registered per field type in the
    schema, not hard-coded per pipeline" -- so it is passed in rather than
    inferred from the value, which would make the scorer's behaviour depend on
    what the model happened to return.

    There is deliberately no default. A field whose kind nobody stated is a field
    nobody decided how to score, and quietly falling back to string equality is
    how `FREE_TEXT` gets scored deterministically without anyone agreeing to it.
    """

    AMOUNT = "amount"
    DATE = "date"
    REFERENCE = "reference"
    ENUM = "enum"
    BOOLEAN = "boolean"
    FREE_TEXT = "free_text"

    @property
    def needs_a_judge(self) -> bool:
        """Whether this kind is R7.11's business rather than this module's."""
        return self is FieldKind.FREE_TEXT


class Verdict(Enum):
    """What scoring one field concluded."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    NEEDS_JUDGE = "needs judge"


class GoldField(BaseModel):
    """One human-verified answer.

    `value=None` means the document does not state this field, verified by a
    person -- which is a scorable answer and not a missing one. A field nobody
    verified is absent from the gold mapping entirely.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float | int | str | bool | None = None
    currency: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class FieldScore:
    """One field's verdict, and why it came out that way.

    `detail` is not decoration: it is what `review.jsonl` shows a person, and
    R7.4 requires an ungrounded field to be distinguishable there from a value
    that simply disagreed.
    """

    field: str
    verdict: Verdict
    detail: str | None = None
    # Whether a judge decided this verdict (R7.17). Carried so a field's total
    # can say how many of its verdicts were judged rather than implying it.
    judged: bool = False

    @property
    def correct(self) -> bool:
        return self.verdict is Verdict.CORRECT


@dataclass(frozen=True)
class DocumentScore:
    """Every scored field for one document, and what was left unscored."""

    document: str
    results: tuple[FieldScore, ...] = ()
    not_in_gold: tuple[str, ...] = ()

    @property
    def scored(self) -> tuple[FieldScore, ...]:
        """The fields with a verdict: deterministic, or judged (R7.17).

        A field still awaiting a judge is not scored. It stays out of the total
        rather than counting as anything, which is what a withheld field looks
        like from here: nobody asked, so nothing is known.
        """
        return tuple(r for r in self.results if r.verdict is not Verdict.NEEDS_JUDGE)


def with_judged(
    score: DocumentScore, verdicts: Mapping[str, tuple[bool, str]]
) -> DocumentScore:
    """A document's score with the judge's verdicts in place of its deferrals (R7.17).

    The judge decides only what was left to it: a field the deterministic
    scorers already decided keeps its verdict, and a deferred field with no
    verdict here -- withheld, so never asked -- stays deferred. The evidence is
    the reason a person reads, as an ungrounded span is for R7.4.
    """
    results = []
    for result in score.results:
        if result.verdict is Verdict.NEEDS_JUDGE and result.field in verdicts:
            supported, evidence = verdicts[result.field]
            results.append(
                FieldScore(
                    result.field,
                    Verdict.CORRECT if supported else Verdict.INCORRECT,
                    evidence,
                    judged=True,
                )
            )
        else:
            results.append(result)
    return DocumentScore(
        document=score.document, results=tuple(results), not_in_gold=score.not_in_gold
    )


def score_field(
    *, record: FieldRecord, gold: GoldField, check: FieldCheck, kind: FieldKind
) -> FieldScore:
    """Score one produced field against one verified answer.

    `check` is the grounding verdict from spec 006, passed in rather than
    recomputed: whether a span was locatable is a fact about the documents the
    stage read, which this function does not have and should not need (R7.4).
    """
    if check.verdict is FieldVerdict.UNGROUNDED:
        # Before any comparison, so a value that happens to match gold cannot
        # rescue a field with no evidence behind it (R7.4).
        return FieldScore(
            record.field,
            Verdict.INCORRECT,
            "ungrounded: the value may be right, and nothing in the document shows it",
        )

    if check.verdict is FieldVerdict.INVALID:
        return FieldScore(record.field, Verdict.INCORRECT, check.detail or "invalid record")

    abstained = record.value is None
    expected_null = gold.value is None

    if abstained and expected_null:
        return FieldScore(record.field, Verdict.CORRECT, "abstained, and gold abstains")
    if abstained:
        return FieldScore(
            record.field, Verdict.INCORRECT, f"abstained; gold states {gold.value!r}"
        )
    if expected_null:
        return FieldScore(
            record.field,
            Verdict.INCORRECT,
            f"answered {record.value!r}; gold abstains, so the correct answer was to "
            "abstain too",
        )

    # Only now, and only for a value that is present and grounded. The three
    # checks above are deterministic whatever the field holds: whether a span was
    # locatable, and whether the run abstained, are facts rather than judgements.
    # R7.3's own examples are all `root_cause`, a free-text field -- so deferring
    # to a judge first would leave the rule with nothing it could score, and R7.4
    # admits no exception for free text either.
    if kind.needs_a_judge:
        return FieldScore(record.field, Verdict.NEEDS_JUDGE, "free text; scored by a judge")

    if not _same_currency(record.currency, gold.currency):
        return FieldScore(
            record.field,
            Verdict.INCORRECT,
            f"currency {record.currency!r} does not match gold {gold.currency!r}",
        )

    comparison = _compare(kind, record.value, gold.value)
    if comparison is None:
        return FieldScore(
            record.field,
            Verdict.INCORRECT,
            f"{record.value!r} is not a well-formed {kind.value}, so it cannot be "
            f"compared with {gold.value!r}",
        )
    if comparison:
        return FieldScore(record.field, Verdict.CORRECT)
    return FieldScore(
        record.field, Verdict.INCORRECT, f"{record.value!r} does not match {gold.value!r}"
    )


def score_document(
    *,
    document: str,
    records: Sequence[FieldRecord],
    checks: Mapping[str, FieldCheck],
    gold: Mapping[str, GoldField],
    kinds: Mapping[str, FieldKind],
) -> DocumentScore:
    """Score every field of one document that gold has an answer for.

    Fields in the output that gold says nothing about are reported separately
    rather than scored or silently dropped -- a growing `not_in_gold` is how a
    gold set falls behind a pipeline, and it should be visible.
    """
    results = tuple(
        score_field(
            record=record,
            gold=gold[record.field],
            check=checks[record.field],
            kind=kinds[record.field],
        )
        for record in records
        if record.field in gold
    )
    return DocumentScore(
        document=document,
        results=results,
        not_in_gold=tuple(
            sorted({record.field for record in records if record.field not in gold})
        ),
    )


@dataclass(frozen=True)
class FieldTotal:
    """One field's deterministic verdicts, summed across every scored document (R7.2)."""

    field: str
    correct: int
    scored: int
    # How many of `scored` a judge decided (R7.17): printed, never implied.
    judged: int = 0

    @property
    def percentage(self) -> float:
        return 100.0 * self.correct / self.scored


def per_field(
    scores: Sequence[DocumentScore], *, declared: Sequence[str]
) -> tuple[FieldTotal, ...]:
    """Each declared field's total across the documents, in declared order.

    Per field, because that is the headline R7.2 requires: a field at 50% and one
    at 100% need different work, and a single blended figure hides which is
    which. Declared order rather than sorted, so the report reads the way the
    declaration does.

    A field no document scored has no total, rather than a total of zero -- a
    0.0% would read as a field that was always wrong.
    """
    totals: list[FieldTotal] = []
    for field in declared:
        results = [r for score in scores for r in score.scored if r.field == field]
        if results:
            totals.append(
                FieldTotal(
                    field=field,
                    correct=sum(1 for r in results if r.correct),
                    scored=len(results),
                    judged=sum(1 for r in results if r.judged),
                )
            )
    return tuple(totals)


def overall(totals: Sequence[FieldTotal]) -> FieldTotal | None:
    """Every verdict in `totals` as one figure, or `None` when nothing was scored.

    R7.2 lets this be printed, and only beside the breakdown it sums: 16 of 20
    reads as 80.0% and says nothing about the field at 50.0%. It is a sum of
    verdicts rather than a mean of percentages, so a field scored on four
    documents weighs what four verdicts weigh.
    """
    if not totals:
        return None
    return FieldTotal(
        field="overall",
        correct=sum(total.correct for total in totals),
        scored=sum(total.scored for total in totals),
    )


def weakest(totals: Sequence[FieldTotal]) -> tuple[str, ...]:
    """The fields at the lowest score, when there is a lowest (R7.2 example 3).

    Compared by cross-multiplying the counts rather than as percentages, so 1/3
    and 2/6 tie however floating point rounds them. Every field tied at the
    minimum is named, since picking one of them would be arbitrary. And when
    every field scores the same, none is: a marker on each line, or on one line
    chosen at random, says nothing about where the work is.
    """
    if not totals:
        return ()
    lowest = totals[0]
    for total in totals[1:]:
        if total.correct * lowest.scored < lowest.correct * total.scored:
            lowest = total
    tied = tuple(
        total.field
        for total in totals
        if total.correct * lowest.scored == lowest.correct * total.scored
    )
    return () if len(tied) == len(totals) else tied


@dataclass(frozen=True)
class FieldDelta:
    """One field's score in two runs, for the change gate (R7.8)."""

    field: str
    before: FieldTotal | None
    after: FieldTotal | None

    @property
    def delta(self) -> float | None:
        """How many points the field moved, or `None` where one run did not score it."""
        if self.before is None or self.after is None:
            return None
        return self.after.percentage - self.before.percentage

    @property
    def regressed(self) -> bool:
        """Whether the field got worse. Compared by cross-multiplying the counts,
        so a field at 2/3 and one at 4/6 did not move however floating point
        rounds them."""
        if self.before is None or self.after is None:
            return False
        return self.after.correct * self.before.scored < self.before.correct * self.after.scored


def regressed_fields(rows: Sequence[FieldDelta]) -> tuple[str, ...]:
    """The fields that got worse, in the order the report lists them (R11.9).

    The one thing a person opens a comparison to find, named so it can be
    filtered on rather than read out of a table. In report order because the tag
    it becomes should read as the report reads; sorting it would put a second
    ordering on the same list for no reason.

    An empty result is a real answer -- nothing regressed -- and the caller
    records it as such rather than omitting the tag (R11.9 row 3).
    """
    return tuple(row.field for row in rows if row.regressed)


def compare_totals(
    before: Sequence[FieldTotal], after: Sequence[FieldTotal]
) -> tuple[FieldDelta, ...]:
    """Every field either run scored, in the order `before` lists them (R7.8).

    A field that did not move is reported with a delta of zero rather than left
    out: a silent row is indistinguishable from a missing one (R7.8 row 4). A
    field only one run scored is still listed, with no delta.
    """
    earlier = {total.field: total for total in before}
    later = {total.field: total for total in after}
    fields = [total.field for total in before] + [
        total.field for total in after if total.field not in earlier
    ]
    return tuple(FieldDelta(field, earlier.get(field), later.get(field)) for field in fields)


def check_same_documents(
    before: Collection[str], after: Collection[str], *, runs: tuple[str, str]
) -> None:
    """Raise `ValueError` naming what differs if two runs covered different documents.

    Scores over different documents are not comparable: a field can move because
    the documents did, and a delta would report that as the change's effect
    (R7.8 row 3). Sorted, so the message is the same on every machine.
    """
    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))
    if only_before or only_after:
        differences = [
            f"only in {run}: {', '.join(keys)}"
            for run, keys in zip(runs, (only_before, only_after), strict=True)
            if keys
        ]
        raise ValueError(
            f"runs {runs[0]} and {runs[1]} cover different documents -- "
            + "; ".join(differences)
            + ". A comparison over different documents is not a comparison."
        )


def check_same_reference(
    before: ResolvedPlan, after: ResolvedPlan, *, runs: tuple[str, str]
) -> None:
    """Raise `ValueError` naming what differs if two runs were shown different context.

    A procedure moves a field as surely as a document does, so a delta over two
    runs shown different procedures would credit the configuration with the
    procedure's change (R7.35, R7.8's reason one level out). Compared by
    snapshot as well as by key: a procedure tightened in place keeps its key,
    and that is how procedures usually change.

    Only when some step of either run reads `reference`. A pipeline declaring
    reference sources that no step reads pins them all the same, and showed no
    call anything (R7.35 row 5).
    """
    if not any(reads_reference(step.inputs) for plan in (before, after) for step in plan.steps):
        return
    shown = [{d.key: d.snapshot for d in plan.reference} for plan in (before, after)]
    changed = sorted(
        key for key in shown[0].keys() & shown[1].keys() if shown[0][key] != shown[1][key]
    )
    differences = [f"{key} changed" for key in changed] + [
        f"only in {run}: {', '.join(keys)}"
        for run, keys in zip(
            runs,
            (
                sorted(shown[0].keys() - shown[1].keys()),
                sorted(shown[1].keys() - shown[0].keys()),
            ),
            strict=True,
        )
        if keys
    ]
    if differences:
        raise ValueError(
            f"runs {runs[0]} and {runs[1]} were shown different reference documents -- "
            + "; ".join(differences)
            + ". A field can move because its context did."
        )


def _same_currency(produced: str | None, expected: str | None) -> bool:
    """Currencies match, or neither field has one.

    CHF 48'200 and EUR 48'200 are different losses, so a matching magnitude is
    not a matching answer.
    """
    if expected is None:
        return True
    return (produced or "").upper() == expected.upper()


def _compare(kind: FieldKind, produced: object, expected: object) -> bool | None:
    """Whether two answers of this kind mean the same thing.

    `None` means "not a well-formed value of this kind", which is a third answer
    and not a `False`: a date the scorer cannot read is a different finding from
    a date that disagrees, and reporting it as a mismatch would send someone
    looking for a discrepancy rather than a malformed field.

    Dispatching on the declared kind rather than sniffing the value is what makes
    this deterministic in the way R7.1 claims. A universal normaliser that tried
    number, then date, then text would score the same pair differently depending
    on what the model happened to return.
    """
    if kind is FieldKind.AMOUNT:
        return _both(_as_number(produced), _as_number(expected))
    if kind is FieldKind.DATE:
        return _both(_as_date(produced), _as_date(expected))
    if kind is FieldKind.BOOLEAN:
        return _both(_as_boolean(produced), _as_boolean(expected))
    # REFERENCE and ENUM are both closed vocabularies compared as text. Which
    # case a model echoed a value back in is not information (R7.1).
    return _folded(produced) == _folded(expected)


def _both(produced: object, expected: object) -> bool | None:
    """Compare two parsed values, or `None` if either would not parse."""
    if produced is None or expected is None:
        return None
    return produced == expected


def _as_number(value: object) -> float | None:
    """A value as a number, or `None` if it is not one.

    Handles the forms a page and a model actually produce: a float, a bare
    numeric string, thousands separators in either convention, and a three-letter
    currency written before or after the amount.
    """
    if isinstance(value, bool):
        # `True == 1` in Python, and a boolean field is not an amount.
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None

    text = _CURRENCY_SUFFIX.sub("", _CURRENCY_PREFIX.sub("", value.strip()))
    text = _THOUSANDS.sub("", text)

    if "," in text:
        whole, _, fraction = text.partition(".")
        if not _COMMA_GROUPS.match(whole):
            # A comma that does not group threes. `48,20` is 48.20 to most of
            # Europe and 4820 to a naive stripper, and there is no way to tell
            # from the value which was meant.
            return None
        text = whole.replace(",", "") + (f".{fraction}" if fraction else "")

    try:
        return float(text)
    except ValueError:
        return None


def _as_boolean(value: object) -> bool | None:
    """A value as a truth value, or `None` if it is not a boolean (R7.36).

    `true` and `false`, or the strings `"true"` and `"false"` in any case:
    whether a model quoted a JSON value is not information, as the case of an
    enum is not. Nothing else -- `1` is a number and `yes` is a word, and reading
    either would begin a vocabulary (`y`, `on`, `ja`) nobody agreed to.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return {"true": True, "false": False}.get(value.strip().casefold())
    return None


def _as_date(value: object) -> date | None:
    """A value as a date, or `None` if it is not one in a form we accept.

    Only unambiguous forms. `07/08/2026` is August in one country and July in
    another, and a scorer that picked one would be quietly wrong for half of
    every year -- so anything not matching a known pattern is not a date here.
    """
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    iso = _ISO.match(text)
    if iso:
        return _date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    little = _LITTLE_ENDIAN.match(text)
    if little:
        first, second = int(little.group(1)), int(little.group(2))
        if first <= 12 and second <= 12:
            # `07/08/2026` is 7 August in one country and 8 July in another. The
            # docstring above has always claimed this is refused rather than
            # guessed; until /quality found it, the code guessed day-first.
            # Refusing is the only answer that cannot be quietly wrong.
            return None
        return _date(int(little.group(3)), second, first)
    return None


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _folded(value: object) -> str:
    """Text compared without case or surrounding whitespace.

    An enum's values are a closed set agreed in the schema; which case a model
    echoed them back in is not information.
    """
    return str(value).strip().casefold()
