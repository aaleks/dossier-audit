"""The gold set, and what it takes to change it (spec 007).

The gold set is the asset the whole system is measured against, so an edit to it
is a change to the definition of correct. Every score `dossier` has ever reported
is a claim about agreement with this data.

The failure that guards against is quiet and slow. Someone corrects a field to
make a run look right; months later nobody can tell whether the model was wrong
or the gold was; and the figure quoted in a meeting is measuring agreement with
an edit nobody reviewed. Attribution is what makes that answerable, and it is
cheap only if it is impossible to skip -- so a correction that carries no
reviewer is refused rather than defaulted (R7.7).

Nothing here writes to `gold/`. This module decides what a correction must carry
and what applying one produces; putting it on disk is a later slice, and it has a
human in it by design.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dossier.domain.hashing import content_hash
from dossier.domain.scoring import GoldField


class AnonymousCorrection(ValueError):
    """A correction arrived with no reviewer behind it.

    There is no anonymous path into the gold set. An unattributed edit is
    indistinguishable from a reviewed one the moment it lands, and the whole
    value of the gold set is that a person stood behind each answer.
    """


class Correction(BaseModel):
    """One reviewer's decision about one field.

    Deliberately carries a reviewer and a date and nothing about a run. Only a
    reviewer's decision enters the gold set, never a model's (R7.7 example 4) --
    and the strongest form of that guarantee is having nowhere to put a run id or
    a confidence score rather than a check that rejects one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    value: float | int | str | bool | None = None
    verified_by: str
    verified_at: date
    # Why the answer is what it is. Required in spirit for an abstention, since
    # R7.3 scores a gold null against a run that abstains and a bare null is
    # indistinguishable from a field nobody filled in.
    reason: str | None = None


class GoldDocument(BaseModel):
    """One document's verified answers, as `gold/<name>/<document>.json` holds them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: str
    verified_by: str
    verified_at: date
    fields: dict[str, dict[str, Any]] = {}


class UnreadableGold(ValueError):
    """Gold files that cannot be read as verified answers, one line each (R7.56)."""

    def __init__(self, lines: Sequence[str]) -> None:
        self.lines = tuple(lines)
        super().__init__("\n".join(self.lines))


# Every shape a gold value can take, in the words of the person writing one.
_GOLD_VALUES = "a number, a string, true or false, a list of strings, or null"


def read_gold_file(name: str, text: str) -> GoldDocument:
    """One gold file's verified answers, or `UnreadableGold` naming what stops them (R7.56).

    A file that does not read stopped `eval` on a traceback, the parser's or
    pydantic's, naming neither the file nor the field. Each answer is read as
    scoring reads it, so a value no scorer can take is refused here, before
    anything is scored, rather than partway through.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        # Where it stopped, and not the parser's words, which change between
        # Python versions.
        raise UnreadableGold(
            [f"{name}: not JSON (line {error.lineno}, column {error.colno})"]
        ) from error
    try:
        document = GoldDocument.model_validate(data)
    except ValidationError as error:
        raise UnreadableGold(_explained(name, error)) from error
    lines: list[str] = []
    for field, entry in document.fields.items():
        scored = {key: entry[key] for key in GoldField.model_fields if key in entry}
        try:
            GoldField.model_validate(scored)
        except ValidationError as error:
            lines += _explained(name, error, field=field)
    if lines:
        raise UnreadableGold(lines)
    return document


def _explained(name: str, error: ValidationError, *, field: str | None = None) -> list[str]:
    """One line per key pydantic refused, in words a person editing the file can act on.

    A value no member of a union accepts is refused once per member; the first
    says it, and the rest would repeat it.
    """
    lines: list[str] = []
    seen: set[object] = set()
    for problem in error.errors():
        location = problem["loc"]
        if location[:1] in seen:
            continue
        seen.add(location[:1])
        # A field's own keys are named under it: `loss_amount.currency`.
        where = ".".join(str(part) for part in (*([field] if field else []), *location))
        if field is not None and location[:1] == ("value",):
            said = f"{field} holds {problem['input']!r}, and a gold value is {_GOLD_VALUES}"
        elif problem["type"] == "missing":
            said = f"{where} is missing"
        elif problem["type"].startswith("date"):
            said = f"{where} {problem['input']!r} is not a date, written as 2026-09-15"
        else:
            # Pydantic's words, where no plainer ones are written (R7.56 row 7).
            said = f"{where}: {problem['msg']}"
        lines.append(f"{name}: {said}")
    return lines


class CalibrationCase(BaseModel):
    """One human-scored case a judge is measured on, as a sample line holds it (R7.16).

    Not a `GoldDocument`. That says what the right value *is*; this says whether a
    *candidate* answer is supported by its document, which is the question a judge
    is asked and the only one its agreement can be measured on. A sample has to be
    able to hold an answer that is wrong -- R7.12's planted case is exactly that --
    and a gold file has nowhere to put one.

    Extra keys are ignored rather than refused, which is the one place this
    differs from every other model here. The sample R7.11 was measured on carries
    `id`, `rule`, `field` and `path` beyond the four a measurement reads, and a
    reviewer's own bookkeeping is not an error.

    `supported` is strict on purpose, and only `supported`. Pydantic would
    otherwise read the *string* `"false"` as `False`, so a malformed sample would
    measure a judge against verdicts its author never wrote and report a
    percentage for it. Strictness is scoped to this one field because
    `verified_at` arrives from JSON as a string and is meant to be parsed.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    document: str
    answer: str
    supported: bool = Field(strict=True)
    verified_by: str
    verified_at: date | None = None
    # The reviewer's justification. Not required, and not read by any
    # measurement: it exists for the person reading a disagreement back.
    reason: str | None = None


def apply_correction(
    document: GoldDocument, correction: Correction, *, today: date | None = None
) -> GoldDocument:
    """The gold document a reviewer's decision produces (R7.7).

    Returns a new document rather than editing in place. A gold set is read by a
    scorer and written by a reviewer, and an in-place edit would let a scoring
    run see a half-applied correction -- frozen models make that structural
    rather than a convention.

    The superseded value travels with the field. The file is committed to git, so
    history is the primary record, but a correction that silently replaced a
    value would make a diff show *that* something changed without showing what it
    displaced, in the same place a reviewer is reading.

    `today` is a parameter because this layer takes its clock rather than reading
    one (R0.4). It is only used to refuse a future date.
    """
    if not correction.verified_by.strip():
        raise AnonymousCorrection(
            f"a correction to {correction.field!r} on {document.document!r} carries no "
            "reviewer. There is no anonymous path into the gold set: an unattributed "
            "edit is an unaudited change to the definition of correct (R7.7)."
        )

    if today is not None and correction.verified_at > today:
        raise ValueError(
            f"{correction.field!r} is verified at {correction.verified_at}, which is "
            f"after {today}. A future date is a clock problem or a typo, and either "
            "way it sorts wrongly against every other correction forever."
        )

    previous = document.fields.get(correction.field, {})
    entry: dict[str, Any] = {
        "value": correction.value,
        "verified_by": correction.verified_by,
        "verified_at": correction.verified_at.isoformat(),
    }
    if correction.reason is not None:
        entry["reason"] = correction.reason
    if "value" in previous:
        # Absent rather than null where there was nothing before: a field review
        # *added* has no superseded value, and recording `None` would read as
        # "it used to be an abstention".
        entry["superseded"] = previous["value"]

    return document.model_copy(update={"fields": {**document.fields, correction.field: entry}})


def gold_set_hash(files: Mapping[str, bytes]) -> str:
    """One hash for a whole gold set: every file's name and content (R11.3, R0.7).

    Two evals over gold sets that differ by one answer are not comparable, and
    this is what says so. Sorted by name before hashing, so the same set gives
    the same hash on every machine however its files were listed (R5.6); each
    file contributes its name and the hash of its content, so renaming a file
    moves the hash as surely as editing one.
    """
    lines = "".join(f"{name}\0{content_hash(files[name])}\n" for name in sorted(files))
    return content_hash(lines.encode("utf-8"))
