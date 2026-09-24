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
import unicodedata
from collections.abc import Collection, Mapping
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


def fold(text: str) -> str:
    """`text` with what a reader cannot tell apart made the same (spec 006).

    Applied to both the span and the document, as whitespace normalisation is and
    for the same reason: either side may be where the difference came from.

    Unicode compatibility forms first (R6.17): NFKC is the normalisation whose
    purpose this is -- `ﬁ` is `fi`, a full-width `Ｃ` is `C`, and a decomposed
    accent is the one a keyboard types. It folds no letter into another and
    never touches case.
    """
    return normalise_whitespace(unicodedata.normalize("NFKC", text))


def locate_span(span: str, *, document_text: str) -> bool:
    """Whether `span` occurs in `document_text`, once both are folded.

    Case-sensitive, deliberately. Case-folding would let a field citing
    `MAJOR` claim support from a document that says `major`, and a span is meant
    to be what the document says rather than an approximation of it. What is
    folded is decided in spec 006 and nowhere else: a relaxation made quietly
    here would change scores with nothing to review.
    """
    needle = fold(span)
    if not needle:
        # An empty string is a substring of every document. Treating it as
        # located would let a field cite nothing and pass, which is the one
        # outcome that makes the whole check decorative (R6.6).
        return False

    return needle in fold(document_text)


# The page marker a converter writes ahead of each page's text, and the only
# thing that makes `source.page` a derived fact rather than a claim (R6.14).
#
# An HTML comment for two reasons. It is invisible wherever the artifact is
# rendered, so the text a person reads is the text the document had. And it is
# not something PDF extraction produces: a bare `Page 3` would be indistinguishable
# from the printed footer on page 12 of a corporate template, and the page would
# then be derived from the wrong thing entirely.
#
# It lives here rather than beside the converter that writes it because both
# sides must agree, and a format written down in two places is a format that
# eventually differs. A converter imports this; `domain` never imports a
# converter.
_PAGE_ANCHOR = re.compile(r"<!--\s*page\s+(\d+)\s*-->")


def page_anchor(page: int) -> str:
    """The marker a converter emits ahead of page `page`. 1-based (R6.14)."""
    return f"<!-- page {page} -->"


def split_pages(text: str) -> list[str]:
    """The pages in converted text, in order.

    The inverse of what a converter did. Nothing in a run needs it -- grounding
    searches the whole document (R6.4) -- but a converter author and a test both
    do, and defining it beside the format is what stops the format being written
    down twice.

    Text with no anchors is one page worth of text rather than zero: the caller
    asked to split something that has no splits in it, and the honest answer is
    what they passed in.
    """
    parts = _PAGE_ANCHOR.split(text)
    if len(parts) == 1:
        return [text]
    # `re.split` with one capture group yields [before, page, text, page, text...].
    # The leading element is whatever preceded the first anchor, which for a
    # converter's own output is empty.
    return parts[2::2]


def page_of_span(span: str, *, document_text: str) -> int | None:
    """The page the located span sits on, or `None` (R6.14).

    `None` covers three different situations on purpose, because all three mean
    the same thing to a reader: there is no page to turn to. The document has no
    anchors, the span is not in it, or nothing was claimed at all.

    Searched in the folded text, exactly as `locate_span` does. The two must
    agree -- a span that grounds and then has no page would be the halves of one
    check disagreeing about the same document -- and folding is what lets them
    share one index. The anchors survive folding: nothing in one is folded.
    """
    needle = fold(span)
    if not needle:
        # An empty span is located nowhere (R6.6). Without this it would land at
        # position zero and be credited to the first anchor in the document.
        return None

    haystack = fold(document_text)
    at = haystack.find(needle)
    if at < 0:
        return None

    preceding = [match for match in _PAGE_ANCHOR.finditer(haystack) if match.start() <= at]
    if not preceding:
        return None
    return int(preceding[-1].group(1))


def with_derived_page(
    record: FieldRecord,
    *,
    input_documents: Mapping[str, str],
) -> FieldRecord:
    """The same record, with `source.page` read from the document (R6.14).

    Replaced rather than compared. The model's number was never evidence of
    anything, so a rule that reported a disagreement would be treating it as
    though it were -- and would turn one real finding, "this page is unverified",
    into a stream of cosmetic ones.

    Returned unchanged, and identically, in the three cases where there is
    nothing to derive against: an abstaining field has no source at all (R6.5),
    and a field citing a document this stage never read is R6.3's finding to
    make rather than this function's to paper over.
    """
    if record.source is None:
        return record

    text = input_documents.get(record.source.document)
    if text is None:
        return record

    page = page_of_span(record.source.span, document_text=text)
    if page == record.source.page:
        return record

    return record.model_copy(update={"source": record.source.model_copy(update={"page": page})})


# The two states a judged verdict can be reached in, as `judge.yaml` names them
# (R7.20). `grounded` rather than `valid`: the file is written by a person and
# read by one, and `valid` is this module's word for the same thing from the
# inside. Defined here because the config layer may import the domain and not
# the other way round, and because a state name in two places drifts.
GROUNDED = "grounded"
DESCRIBED = "described"
JUDGED_STATES = (GROUNDED, DESCRIBED)


def judged_states(*, per_part: bool) -> tuple[str, ...]:
    """The states a pipeline can produce a judged verdict in (R7.20, R7.23).

    A `per_part` step is the only thing that hands a stage a picture (R3.12), so
    it is the only thing that can produce a `described` verdict. Asked in one
    place because two callers must agree: the loader refuses a pipeline missing
    a bar for a state it can reach, and the gate withholds a field missing a
    calibration for one -- and a pipeline refused for a bar it then never needed
    would be the worse of the two mistakes.
    """
    return JUDGED_STATES if per_part else (GROUNDED,)


def judge_name(field: str, state: str) -> str:
    """What a judge's sample and calibration are filed under (R7.22).

    `root_cause` for the grounded judge and `root_cause.described` for the other,
    rather than a directory per state. The grounded name is unchanged, so every
    gold set written before there were two states is read by the same path --
    the same bargain the scalar threshold makes in `judge.yaml` (R7.20 row 2).
    """
    return field if state == GROUNDED else f"{field}.{state}"


class FieldVerdict(Enum):
    """What a checked field record turned out to be (spec 006).

    Five outcomes rather than a boolean, because the spec draws three different
    lines and collapsing them would lose the one that matters most: an
    `ungrounded` field has a plausible value and no evidence, which is a
    completely different problem from a malformed record, and is scored
    incorrect even when the value happens to match gold (R7.4).
    """

    VALID = "valid"
    ABSTAINED = "abstained"
    DESCRIBED = "described"
    UNGROUNDED = "ungrounded"
    INVALID = "invalid"

    @property
    def is_failure(self) -> bool:
        """Abstention is never a failure (R6.5), and neither is a description.

        `described` sits where `ungrounded` would, and is the opposite claim:
        the evidence is on a page the model looked at, and a string search is
        simply the wrong instrument for it (R6.15). Counting it as a failure
        would score honest visual evidence as fabrication; counting it as a
        pass would let an unverifiable claim through as a checked one. It is
        neither, and R7.21's judge is what decides it.
        """
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
    shown_as_pictures: Collection[str] = (),
) -> FieldCheck:
    """Check one extracted field against the documents its stage actually read.

    `input_documents` maps document key to converted text. Passing the text in
    rather than a lookup is what keeps this a pure function -- and what makes
    R6.3 checkable at all, because "is an input to that stage" is a fact about
    the caller, not about the field.

    `shown_as_pictures` names the documents this stage read as page images
    (R6.15). It is passed rather than inferred from a document being absent
    from `input_documents`: those two are not the same thing at all, and
    guessing would turn every citation of a document the stage never saw into
    a description of one it did (R6.3).
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

    shown = record.source.document in shown_as_pictures
    if record.source.document not in input_documents and not shown:
        # Worse than no citation, because it looks checkable. A reviewer opening
        # the named document would find it was never part of this stage.
        return FieldCheck(
            FieldVerdict.INVALID,
            f"{record.field}: cites {record.source.document!r}, which was not an "
            f"input to this stage. Inputs were {sorted(input_documents)} (R6.3).",
        )

    if not locate_span(
        record.source.span, document_text=input_documents.get(record.source.document, "")
    ):
        # A picture is why the search failed, not an excuse for what it found.
        # An empty span is excluded here rather than by `locate_span` returning
        # something richer: it is a substring of every document and of no page,
        # so letting it through as `described` would make citing nothing the
        # cheapest way to avoid a failure (R6.6, R6.15).
        if shown and normalise_whitespace(record.source.span):
            return FieldCheck(
                FieldVerdict.DESCRIBED,
                f"{record.field}: read off {record.source.document}, which this stage "
                "was shown as page images. No text to search, so the span is not "
                "locatable and a judge decides it (R6.15).",
            )
        return FieldCheck(
            FieldVerdict.UNGROUNDED,
            f"{record.field}: span not found in {record.source.document} (R6.4).",
        )

    return FieldCheck(FieldVerdict.VALID)
