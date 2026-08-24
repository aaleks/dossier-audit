"""Checking that a value points at evidence (spec 006).

The whole of this module is a string search. That is the point: the design deck's
claim is that grounding is *checkable without a model*, and the moment it needs a
judgement it stops being free and starts being another thing to calibrate.

A field whose span cannot be located is `ungrounded` and fails, regardless of how
plausible its value looks (R6.4), and is scored incorrect even when the value
matches gold (R7.4).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from dossier.domain.schemas import FieldRecord

# `\s` under Python 3's default unicode matching covers the ordinary whitespace
# plus U+00A0, which PDF text extraction emits inside figures like `CHF 48'200`.
# A reader cannot see the difference, so neither should the check.
_WHITESPACE = re.compile(r"\s+")


def normalise_whitespace(text: str) -> str:
    """Collapse every run of whitespace to one space, and strip.

    Applied to both the span and the document. A converter that flattened a table
    into running text is as likely to be the source of a difference as the model
    is, so normalising only the model's side would fail honest citations.

    Idempotent: text moves between stages and may pass through here more than
    once, and a normalisation that drifted on a second application would make
    grounding depend on how many times it had been called.
    """
    return _WHITESPACE.sub(" ", text).strip()


def locate_span(span: str, *, document_text: str) -> bool:
    """Whether `span` occurs in `document_text`, after whitespace normalisation.

    Case-sensitive, deliberately. Case-folding would let a field citing
    `MAJOR` claim support from a document that says `major`, and a span is meant
    to be what the document says rather than an approximation of it. If that
    proves too strict against real converted text, it is a spec conversation
    rather than a quiet relaxation here.
    """
    needle = normalise_whitespace(span)
    if not needle:
        # An empty string is a substring of every document. Treating it as
        # located would let a field cite nothing and pass, which is the one
        # outcome that makes the whole check decorative (R6.6).
        return False

    return needle in normalise_whitespace(document_text)


class FieldVerdict(Enum):
    """What a checked field record turned out to be (spec 006).

    Four outcomes rather than a boolean, because the spec draws three different
    lines and collapsing them would lose the one that matters most: an
    `ungrounded` field has a plausible value and no evidence, which is a
    completely different problem from a malformed record, and is scored
    incorrect even when the value happens to match gold (R7.4).
    """

    VALID = "valid"
    ABSTAINED = "abstained"
    UNGROUNDED = "ungrounded"
    INVALID = "invalid"

    @property
    def is_failure(self) -> bool:
        """Abstention is never a failure (R6.5)."""
        return self in (FieldVerdict.UNGROUNDED, FieldVerdict.INVALID)


@dataclass(frozen=True)
class FieldCheck:
    """A verdict, and why -- the `why` ends up in `review.jsonl` (spec 007)."""

    verdict: FieldVerdict
    detail: str | None = None

    @property
    def is_failure(self) -> bool:
        return self.verdict.is_failure


def check_field(
    record: FieldRecord,
    *,
    input_documents: Mapping[str, str],
) -> FieldCheck:
    """Check one extracted field against the documents its stage actually read.

    `input_documents` maps document key to converted text. Passing the text in
    rather than a lookup is what keeps this a pure function -- and what makes
    R6.3 checkable at all, because "is an input to that stage" is a fact about
    the caller, not about the field.
    """
    if record.value is None:
        if not record.reason:
            # "Not stated" is a first-class answer, but only when it says why.
            # A bare null is indistinguishable from a field the model forgot.
            return FieldCheck(
                FieldVerdict.INVALID,
                f"{record.field}: value is null with no reason. Abstention must say "
                "why it abstained (R6.5).",
            )
        return FieldCheck(FieldVerdict.ABSTAINED, record.reason)

    if record.source is None:
        return FieldCheck(
            FieldVerdict.INVALID,
            f"{record.field}: has a value and no source. A figure without evidence "
            "is the thing this system exists not to produce (R6.6).",
        )

    if record.source.document not in input_documents:
        # Worse than no citation, because it looks checkable. A reviewer opening
        # the named document would find it was never part of this stage.
        return FieldCheck(
            FieldVerdict.INVALID,
            f"{record.field}: cites {record.source.document!r}, which was not an "
            f"input to this stage. Inputs were {sorted(input_documents)} (R6.3).",
        )

    if not locate_span(
        record.source.span, document_text=input_documents[record.source.document]
    ):
        return FieldCheck(
            FieldVerdict.UNGROUNDED,
            f"{record.field}: span not found in {record.source.document} (R6.4).",
        )

    return FieldCheck(FieldVerdict.VALID)
