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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import FieldRecord

# Separators a person or a model puts in a number. Stripped before comparison,
# because `48'200.00` and `48,200.00` and `48200.00` are one amount written three
# ways and none of them is a different answer (R7.1 example 2).
_THOUSANDS = re.compile(r"[\s'’, ]")

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
        """The fields with a deterministic verdict, judge fields excluded."""
        return tuple(r for r in self.results if r.verdict is not Verdict.NEEDS_JUDGE)


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
    try:
        return float(text)
    except ValueError:
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
