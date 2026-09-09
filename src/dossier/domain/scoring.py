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
    # Free text, scored by a judge against a rubric rather than by comparison
    # (R7.11). Declared on the gold entry because it is a property of the field,
    # and the gold file is where a field's type is agreed.
    judged: bool = False


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
    *, record: FieldRecord, gold: GoldField, check: FieldCheck
) -> FieldScore:
    """Score one produced field against one verified answer.

    `check` is the grounding verdict from spec 006, passed in rather than
    recomputed: whether a span was locatable is a fact about the documents the
    stage read, which this function does not have and should not need (R7.4).
    """
    if gold.judged:
        return FieldScore(record.field, Verdict.NEEDS_JUDGE, "free text; scored by a judge")

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

    if not _same_currency(record.currency, gold.currency):
        return FieldScore(
            record.field,
            Verdict.INCORRECT,
            f"currency {record.currency!r} does not match gold {gold.currency!r}",
        )

    if _matches(record.value, gold.value):
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
            check=checks.get(record.field, FieldCheck(FieldVerdict.VALID)),
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


def _matches(produced: object, expected: object) -> bool:
    """Whether two answers mean the same thing, after normalisation (R7.1).

    Tried in order of how much interpretation each step costs: identical values
    first, then numbers, then dates, then case-folded text. The first that
    applies decides, and a form nothing recognises falls through to a plain
    comparison rather than being guessed at.
    """
    if produced == expected:
        return True

    as_numbers = (_as_number(produced), _as_number(expected))
    if None not in as_numbers:
        return as_numbers[0] == as_numbers[1]

    as_dates = (_as_date(produced), _as_date(expected))
    if None not in as_dates:
        return as_dates[0] == as_dates[1]

    return _folded(produced) == _folded(expected)


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
        return _date(int(little.group(3)), int(little.group(2)), int(little.group(1)))
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
