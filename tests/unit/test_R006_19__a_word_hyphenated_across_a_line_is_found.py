"""R6.19 — a word broken across a line by a hyphen is found joined or hyphenated.

A hyphen that ends a line may be the typesetter's, splitting `certificate`, or
the word's own, in `well-known`. Nothing in the text says which, so the document
is read both ways and a span found in either is located. Its page is the page of
the reading it was found in (R6.14). A soft hyphen (U+00AD) is invisible, and is
dropped.
"""

from __future__ import annotations

import pytest

from dossier.domain.grounding import locate_span, page_of_span

SOFT_HYPHEN = "­"
ROOT_CAUSE = "the renewed certificate was never deployed"


class TestAWordHyphenatedAcrossALineIsFound:
    """R6.19 — a line-end hyphen is read both ways."""

    def test_a_word_split_by_the_typesetter_is_found_whole(self):
        """Row 1: the one where `certificate` broke across two lines."""
        text = "the renewed certifi-\ncate was never deployed"

        assert locate_span(ROOT_CAUSE, document_text=text)

    @pytest.mark.parametrize(
        "line_break",
        ["\n", "\r\n", "  \n  ", "\n\n"],
        ids=["newline", "crlf", "padded", "blank line"],
    )
    def test_any_line_break_after_the_hyphen_is_one(self, line_break: str):
        """Row 1 for each line ending a converter writes: Jira's `\\r\\n`, a PDF's padding."""
        text = f"the renewed certifi-{line_break}cate was never deployed"

        assert locate_span(ROOT_CAUSE, document_text=text)

    def test_a_word_whose_own_hyphen_ends_a_line_is_found_hyphenated(self):
        """Row 2: the one where the hyphen belongs to `well-known`."""
        assert locate_span("a well-known gap", document_text="a well-\nknown gap")

    def test_a_soft_hyphen_is_not_there(self):
        """Row 3: the one where the typesetter hid a hyphenation point."""
        text = f"the renewed certi{SOFT_HYPHEN}ficate was never deployed"

        assert locate_span(ROOT_CAUSE, document_text=text)

    def test_the_page_is_the_page_of_the_reading_it_was_found_in(self):
        """Row 4: the one where row 1's text is on page 2 of three."""
        text = (
            "<!-- page 1 -->\nPostmortem INC-4830\n"
            "<!-- page 2 -->\nthe renewed certifi-\ncate was never deployed\n"
            "<!-- page 3 -->\nAction items"
        )

        assert page_of_span(ROOT_CAUSE, document_text=text) == 2
        assert page_of_span("certifi- cate", document_text=text) is None

    def test_a_hyphen_that_is_not_at_a_line_break_is_the_texts(self):
        """Counter-example, row 5: `pre-` is followed by a space, not a new line."""
        text = "pre- and post-deploy checks"

        assert not locate_span("pre and post-deploy checks", document_text=text)

    def test_a_hyphen_before_a_break_between_numbers_is_left_alone(self):
        """Counter-example: `-` then a line then a digit is a range or a sign, not a word."""
        assert not locate_span("09:1209:54", document_text="09:12-\n09:54")
