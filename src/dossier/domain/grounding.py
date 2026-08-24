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
