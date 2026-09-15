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

from collections.abc import Mapping
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from dossier.domain.hashing import content_hash


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

    return document.model_copy(
        update={"fields": {**document.fields, correction.field: entry}}
    )


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
