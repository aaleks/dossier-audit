"""R6.20 — the markdown a converter wrote around words is not text a span is compared with.

Converters write markdown (spec 008): `**Status:** Done` in a Jira issue's note,
bold and links in Docling's. Strong and emphasis markers, strikethrough, inline
code and link syntax are folded to the words they mark, on both sides. A `*` or
`_` that marks nothing -- inside a word, or unpaired -- is text, as CommonMark
reads it.
"""

from __future__ import annotations

import pytest

from dossier.domain.grounding import locate_span, page_of_span

NOTE = "# INC-4821 — Card payments declined at checkout\n\n**Status:** Done\n**Type:** Incident"


class TestMarkdownAroundWordsIsFolded:
    """R6.20 — a marker is not a word."""

    def test_strong_markers_are_not_part_of_the_text(self):
        """Row 1: the one where a model quotes the words of `INC-4821`'s note."""
        assert locate_span("Status: Done", document_text=NOTE)

    def test_a_span_that_kept_the_markers_is_folded_the_same_way(self):
        """Row 2: the one where the model kept `**`."""
        assert locate_span("**Status:** Done", document_text=NOTE)

    def test_a_link_is_its_text(self):
        """Row 3: the one where a comment links the rollback."""
        text = "Rolled back. see [the rollback](https://git.example/r/77) for the diff"

        assert locate_span("see the rollback for the diff", document_text=text)

    def test_an_image_is_its_alternative_text(self):
        """Row 3's sibling: `![alt](src)` reads as its alt text."""
        text = "Latency: ![p99 latency at 2.4 s](chart.png) during the incident"

        assert locate_span("Latency: p99 latency at 2.4 s during", document_text=text)

    def test_inline_code_is_its_text(self):
        """Row 4: the one where `payments-db` was written as code."""
        text = "the `payments-db` pool was exhausted"

        assert locate_span("the payments-db pool was exhausted", document_text=text)

    @pytest.mark.parametrize(
        "marked",
        ["*renewed*", "_renewed_", "__renewed__", "~~renewed~~", "***renewed***"],
        ids=["emphasis", "underscore emphasis", "underscore strong", "strike", "both"],
    )
    def test_emphasis_is_its_words(self, marked: str):
        """Row 5: the one where `renewed` was emphasised, in each spelling."""
        text = f"the {marked} certificate was never deployed"

        assert locate_span("the renewed certificate was never deployed", document_text=text)

    def test_emphasis_over_several_words_is_its_words(self):
        """Row 5 across a phrase."""
        text = "the **renewed certificate** was never deployed"

        assert locate_span("the renewed certificate was never deployed", document_text=text)

    def test_the_page_follows_the_same_fold(self):
        """The anchor is untouched by the fold, so the page is found (R6.14)."""
        text = "<!-- page 1 -->\nintro\n<!-- page 2 -->\n**Root cause:** the renewed one"

        assert page_of_span("Root cause: the renewed one", document_text=text) == 2

    def test_an_underscore_inside_a_word_and_a_lone_star_are_text(self):
        """Counter-example, row 6: `lb_acq_01` and `3*2` mark nothing."""
        text = "pool lb_acq_01 held 3*2 connections"

        assert not locate_span("pool lbacq01 held 32 connections", document_text=text)
        assert locate_span("pool lb_acq_01 held 3*2 connections", document_text=text)

    def test_a_star_between_spaces_is_text(self):
        """Counter-example: `2 * 3 * 4` is arithmetic, not emphasis."""
        text = "a budget of 2 * 3 * 4 hours"

        assert not locate_span("a budget of 2 3 4 hours", document_text=text)
