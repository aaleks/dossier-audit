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
from dataclasses import dataclass, replace
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

# `90 days`, `1 Year`, and ISO 8601's `P90D`: one whole number and one of four
# units (R7.37). Nothing else is a duration. A bare `90` names no unit, and is
# refused as `07/08/2026` is; `90 business days` is a count on a calendar, not a
# length; `P1Y6M` has two units where `18 months` has one.
_SPELLED = re.compile(r"^(\d+)\s+(day|week|month|year)s?$")
_ISO_DURATION = re.compile(r"^p(\d+)([dwmy])$")
_ISO_UNITS = {"d": "day", "w": "week", "m": "month", "y": "year"}
# Where a length converts exactly (R7.38): a week is seven days and a year is
# twelve months. Nothing converts between the two families. A month is 28 to 31
# days and a year 365 or 366, so three months' notice and ninety days' notice
# are different notice, and equating them would be right only by convention.
_LENGTH = {"day": (1, "day"), "week": (7, "day"), "month": (1, "month"), "year": (12, "month")}


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
    DURATION = "duration"
    LIST = "list"
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

    # A list is the one answer gold writes as an array: the run answers it one
    # record per item, and gold holds the items together (R7.40).
    value: float | int | str | bool | list[str] | None = None
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
    # A list's items beside its verdict (R7.43); `None` for every other kind.
    items: ItemCounts | None = None

    @property
    def correct(self) -> bool:
        return self.verdict is Verdict.CORRECT


@dataclass(frozen=True)
class ItemCounts:
    """What a list's items say beside its one verdict (R7.43).

    `matched` of the `named` items are in gold, out of the `expected` gold holds.
    An item whose record failed its check counts as named and never as matched,
    as an ungrounded value is never right (R7.4).
    """

    matched: int
    named: int
    expected: int

    @property
    def precision(self) -> float | None:
        """Of the items the run named, the share gold names; `None` when it named none."""
        return 100.0 * self.matched / self.named if self.named else None

    @property
    def recall(self) -> float | None:
        """Of gold's items, the share the run named; `None` when gold holds none."""
        return 100.0 * self.matched / self.expected if self.expected else None


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


def judged_pages(pages: Sequence[tuple[str | None, bool, str]]) -> tuple[bool, str]:
    """A field's judged verdict from each page's, each `(part, supported, evidence)` (R7.49).

    Supported only when the judge supported every page that gave a value, as a
    field is correct only when every such page is (R7.48); otherwise the pages
    it did not support, each named with the judge's evidence.
    """
    refused = [(part, evidence) for part, supported, evidence in pages if not supported]
    if not refused:
        return True, pages[0][2]
    return False, "; ".join(
        evidence if part is None else f"{part}: {evidence}" for part, evidence in refused
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
        record.field,
        Verdict.INCORRECT,
        f"{record.value!r} does not match {gold.value!r}"
        + _across_calendar(kind, record.value, gold.value),
    )


def score_list(
    *,
    field: str,
    records: Sequence[FieldRecord],
    checks: Sequence[FieldCheck],
    gold: GoldField,
) -> FieldScore:
    """Score a `list` field's records, one per item, as one answer (R7.40).

    The answer is the set of values its records hold: order is not information,
    and a system two pages name is one system. An item is compared as a
    `reference` is, case folded, and matches whole -- `payments` is not
    `payments-api`, which a substring match would call right.

    A record with no value is an abstention, so a list whose every record
    abstains abstained, and is decided as any field is (R7.3).
    """
    paired = list(zip(records, checks, strict=True))
    named = [record.value for record in records if record.value is not None]
    run = _items(named)
    # A scalar is one item rather than its characters. R7.44 refuses a list
    # written as one string before scoring; this only keeps a string from being
    # read letter by letter should one arrive.
    if gold.value is None:
        expected: dict[str, str] = {}
    else:
        expected = _items(gold.value if isinstance(gold.value, list) else [gold.value])
    # Counted before any verdict, since every verdict carries them (R7.43). Only
    # an item whose evidence held can match: an ungrounded one is named, and is
    # never right (R7.4).
    shown = _items(
        [
            record.value
            for record, check in paired
            if record.value is not None and not check.is_failure
        ]
    )
    counts = ItemCounts(
        matched=len(set(shown) & set(expected)), named=len(run), expected=len(expected)
    )

    def verdict(outcome: Verdict, detail: str | None = None) -> FieldScore:
        return FieldScore(field, outcome, detail, items=counts)

    # Before any comparison, as for any field (R7.4): each item carries its own
    # evidence, and one the document does not show fails the list however well
    # the others are grounded (R7.42). An abstaining record is not a failure
    # (R6.5); beside items it adds nothing, and the list is its items.
    ungrounded = [
        str(record.value)
        for record, check in paired
        if check.verdict is FieldVerdict.UNGROUNDED
    ]
    if ungrounded:
        return verdict(Verdict.INCORRECT, f"ungrounded: {', '.join(ungrounded)}")
    invalid = [
        check.detail or "invalid record"
        for check in checks
        if check.verdict is FieldVerdict.INVALID
    ]
    if invalid:
        return verdict(Verdict.INCORRECT, "; ".join(invalid))

    if not named and gold.value is None:
        return verdict(Verdict.CORRECT, "abstained, and gold abstains")
    if not named:
        return verdict(Verdict.INCORRECT, f"abstained; gold states {gold.value!r}")
    if gold.value is None:
        return verdict(
            Verdict.INCORRECT,
            f"answered {named!r}; gold abstains, so the correct answer was to abstain too",
        )

    missing = sorted(spelled for item, spelled in expected.items() if item not in run)
    extra = sorted(spelled for item, spelled in run.items() if item not in expected)
    if not missing and not extra:
        return verdict(Verdict.CORRECT)
    # Both named, and apart: a system the run missed and one it invented are
    # different mistakes, and R7.25 prints this line to tell them apart.
    detail = "; ".join(
        part
        for part in (
            f"missing: {', '.join(missing)}" if missing else "",
            f"not in gold: {', '.join(extra)}" if extra else "",
        )
        if part
    )
    return verdict(Verdict.INCORRECT, detail)


def _items(values: Sequence[object]) -> dict[str, str]:
    """Each distinct item, folded, with the first spelling it was written in."""
    items: dict[str, str] = {}
    for value in values:
        items.setdefault(str(value).strip().casefold(), str(value).strip())
    return items


def gold_shape_errors(
    document: str, gold: Mapping[str, GoldField], kinds: Mapping[str, FieldKind]
) -> tuple[str, ...]:
    """What is wrong with the shape of one document's gold answers, if anything (R7.44).

    A list is written as an array and nothing else is. Checked against the
    declaration before anything is scored, because an answer in the wrong shape
    is a definition of correct no run can meet -- and scoring against it would
    report the run as wrong rather than the gold set.

    A field the declaration does not have is not this function's business: it is
    reported as not scored, as it always was.
    """
    errors: list[str] = []
    for field, answer in gold.items():
        kind = kinds.get(field)
        if kind is FieldKind.LIST and answer.value == []:
            # A run answering one record per item says "there are none" and "the
            # document does not say" the same way, as an abstention with a
            # reason, so gold cannot usefully hold the difference.
            errors.append(
                f"{document}: {field} is an empty list; write null, with a reason, "
                "for a document that names none"
            )
        elif kind is FieldKind.LIST and not isinstance(answer.value, list | None):
            # Not split on its commas: that would be a guess, and an item may
            # hold a comma. The shape kept from when the field was a `reference`.
            errors.append(
                f"{document}: {field} is a list, and gold writes a list as an array, "
                f'such as ["a", "b"]; found {answer.value!r}'
            )
        elif kind is not None and kind is not FieldKind.LIST and isinstance(answer.value, list):
            errors.append(
                f"{document}: {field} is {kind.value}, and only a list field holds an array"
            )
    return tuple(errors)


def score_document(
    *,
    document: str,
    records: Sequence[FieldRecord],
    checks: Sequence[FieldCheck],
    gold: Mapping[str, GoldField],
    kinds: Mapping[str, FieldKind],
    parts: Sequence[str] = (),
) -> DocumentScore:
    """Score every field of one document that gold has an answer for.

    `checks` pairs with `records` one to one, as a run produces them. Keyed by
    field they collapsed to one check per field, which a list answered one
    record per item cannot survive: every item has its own evidence (R7.42).

    Every field is one verdict, in the place of its first record, however many
    records answered it: a list's items (R7.41), and a `per_part` step's pages
    (R7.46).

    `parts` names the part each record came from, paired with `records`, for a
    `per_part` step; empty for every other step. A field is correct only when
    every page that gave it a value is, and a miss names the page (R7.48).

    Fields in the output that gold says nothing about are reported separately
    rather than scored or silently dropped -- a growing `not_in_gold` is how a
    gold set falls behind a pipeline, and it should be visible.
    """
    named = list(zip(records, checks, parts or [None] * len(records), strict=True))
    results: list[FieldScore] = []
    scored: set[str] = set()
    for record in records:
        if record.field not in gold or record.field in scored:
            continue
        # One verdict per field per document, however many records answered it.
        # A `per_part` step answers once per page, and a field counted per page
        # would weigh a document by how many pages it has (R7.46), as a list
        # counted per item would by how many items it names (R7.41).
        scored.add(record.field)
        kind = kinds[record.field]
        if kind is not FieldKind.LIST:
            results.append(
                _score_pages(
                    [page for page in named if page[0].field == record.field],
                    gold=gold[record.field],
                    kind=kind,
                )
            )
        else:
            items = [(item, of) for item, of, _ in named if item.field == record.field]
            results.append(
                score_list(
                    field=record.field,
                    records=[item for item, _ in items],
                    checks=[of for _, of in items],
                    gold=gold[record.field],
                )
            )
    # A declared field gold verifies and the run gave no record for. Scored only
    # by the records that exist, it had no verdict, and a run that left out
    # every field it was unsure of was never wrong about one -- the thing R7.3
    # exists to prevent. So it is an abstention, named apart because the run
    # said nothing rather than that the document is silent (R7.50).
    for field in kinds:
        if field in gold and field not in scored:
            results.append(_not_answered(field, gold[field]))
    return DocumentScore(
        document=document,
        results=tuple(results),
        not_in_gold=tuple(
            sorted({record.field for record in records if record.field not in gold})
        ),
    )


def _not_answered(field: str, gold: GoldField) -> FieldScore:
    """The verdict on a field the run gave no record for, as an abstention's (R7.50)."""
    if gold.value is None:
        return FieldScore(field, Verdict.CORRECT, "not answered, and gold abstains")
    return FieldScore(field, Verdict.INCORRECT, f"not answered; gold states {gold.value!r}")


def _score_pages(
    pages: Sequence[tuple[FieldRecord, FieldCheck, str | None]],
    *,
    gold: GoldField,
    kind: FieldKind,
) -> FieldScore:
    """One verdict from every record that answered a field, each `(record, check, part)`.

    Each page that gave a value is scored as a `per_file` record is, and held to
    gold rather than to the other pages: `critical` and `Critical` agree because
    each matches gold. One page wrong makes the field wrong, because a run that
    gives two answers to one question has not given the right one -- R6.24's
    reason for refusing a reply that does it, and R7.42's for failing a list with
    one wrong item (R7.48).
    """
    answering = [page for page in pages if page[0].value is not None]
    if not answering:
        # "Not on this page" says nothing about the document while another page
        # answers; only when every page says it is it the document's answer, and
        # scored as one (R7.47). Said so, since no single page is what was wrong.
        record, check, part = pages[0]
        score = score_field(record=record, gold=gold, check=check, kind=kind)
        if part is None or score.detail is None:
            return score
        return replace(
            score, detail=score.detail.replace("abstained;", "abstained on every page;", 1)
        )
    scores = [
        (part, score_field(record=record, gold=gold, check=check, kind=kind))
        for record, check, part in answering
    ]
    wrong = [(part, score) for part, score in scores if score.verdict is Verdict.INCORRECT]
    if wrong:
        return FieldScore(
            scores[0][1].field,
            Verdict.INCORRECT,
            "; ".join(
                score.detail if part is None else f"{part}: {score.detail}"
                for part, score in wrong
            ),
        )
    # Every page is right, or some are still the judge's to decide.
    return next((score for _, score in scores if not score.correct), scores[0][1])


@dataclass(frozen=True)
class FieldTotal:
    """One field's deterministic verdicts, summed across every scored document (R7.2)."""

    field: str
    correct: int
    scored: int
    # How many of `scored` a judge decided (R7.17): printed, never implied.
    judged: int = 0
    # A list's items across the documents (R7.43): reported, and read by no
    # gate. `--compare` decides a regression on `correct` and `scored` alone.
    items: ItemCounts | None = None

    @property
    def percentage(self) -> float:
        return 100.0 * self.correct / self.scored


def describe_items(total: FieldTotal) -> str:
    """A list's items as its report line gives them, or `""` for any other field (R7.43).

    A figure with no items under it is `--` rather than `0.0%`: a run that named
    nothing named nothing wrong, and gold holding nothing leaves nothing to miss.
    """
    if total.items is None:
        return ""
    precision = _share("precision", total.items.matched, total.items.named)
    recall = _share("recall", total.items.matched, total.items.expected)
    return f"items: {precision}, {recall}"


def _share(name: str, part: int, whole: int) -> str:
    return f"{name} {100.0 * part / whole:.1f}% ({part}/{whole})" if whole else f"{name} --"


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
            # Summed rather than averaged per document, so a document naming
            # four systems weighs four items (R7.43).
            counted = [r.items for r in results if r.items is not None]
            totals.append(
                FieldTotal(
                    field=field,
                    correct=sum(1 for r in results if r.correct),
                    scored=len(results),
                    judged=sum(1 for r in results if r.judged),
                    items=ItemCounts(
                        matched=sum(c.matched for c in counted),
                        named=sum(c.named for c in counted),
                        expected=sum(c.expected for c in counted),
                    )
                    if counted
                    else None,
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


type Failure = tuple[str, str, str | None]


def unscored(
    failures: Sequence[Failure],
    *,
    steps: Sequence[str],
    scored: str,
    answered: Collection[str],
) -> list[Failure]:
    """The documents left unscored, each once, as `(step, document, reason)` (R7.53).

    `failures` are the run's, in pipeline order. What leaves a document unscored
    is the scored step having no answer for it: it failed the document, or
    skipped it because a step it reads had failed it (R6.13, R6.28). So a
    document the scored step `answered` is never named, whatever another step
    did to it, and a failure after the scored step is not consulted. Before
    this, a step after the scored one named a scored document as not scored,
    and a document two steps failed was named twice.

    Named at its first failure, because that one left every step after it
    without the document.
    """
    order = {step: at for at, step in enumerate(steps[: steps.index(scored) + 1])}
    named: dict[str, Failure] = {}
    # Sorted by step, stably, so the first failure is the pipeline's first
    # whatever order the failures were collected in.
    for step, document, reason in sorted(
        (failure for failure in failures if failure[0] in order), key=lambda f: order[f[0]]
    ):
        if document not in answered and document not in named:
            named[document] = (step, document, reason)
    return list(named.values())


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
    if kind is FieldKind.DURATION:
        return _both(_as_length(produced), _as_length(expected))
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


def _as_length(value: object) -> tuple[int, str] | None:
    """A duration as a number of days, or of months, whichever its unit is (R7.38)."""
    duration = _as_duration(value)
    if duration is None:
        return None
    count, unit = duration
    factor, base = _LENGTH[unit]
    return count * factor, base


def _across_calendar(kind: FieldKind, produced: object, expected: object) -> str:
    """Why two durations were not compared as lengths, or `""` if they were (R7.38).

    "does not match" alone would send a reviewer to check a number that was
    never the problem. When one side counts days and the other months, the
    reason is the unit, and the detail names it.
    """
    if kind is not FieldKind.DURATION:
        return ""
    sides = [_as_duration(produced), _as_duration(expected)]
    if None in sides or len({_LENGTH[unit][1] for _, unit in sides}) == 1:
        return ""
    unit = next(unit for _, unit in sides if _LENGTH[unit][1] == "month")
    return f": a {unit} is not a fixed number of days, so the two are not compared as lengths"


def _as_duration(value: object) -> tuple[int, str] | None:
    """A value as a number of one unit, or `None` if it is not a duration (R7.37)."""
    if not isinstance(value, str):
        return None
    text = value.strip().casefold()
    spelled = _SPELLED.match(text)
    if spelled:
        return int(spelled.group(1)), spelled.group(2)
    iso = _ISO_DURATION.match(text)
    if iso:
        return int(iso.group(1)), _ISO_UNITS[iso.group(2)]
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
