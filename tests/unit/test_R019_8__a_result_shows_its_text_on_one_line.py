"""R19.8 — a result shows its chunk's text on one line, cut at a word to at
most 200 characters (rows 5 to 7).

The text a person reads first for each result, so one result is one glance: a
chunk's line breaks are spaces, and what does not fit is cut at a word and
marked, so a reader knows there is more. `--json` gives the text whole.
"""

from __future__ import annotations

from dossier.domain.search import excerpt

ROOT_CAUSE = (
    "Certificate renewal and certificate deployment were two separate processes,\n"
    "and only the first was automated."
)


class TestAResultShowsItsTextOnOneLine:
    """R19.8 rows 5 to 7 — one line, at most 200 characters, cut at a word."""

    def test_a_long_text_is_cut_at_the_last_word_that_fits(self):
        """Row 5 — the one where the 200th character falls inside a word."""
        text = "\n".join(" ".join(["incident"] * 10) for _ in range(3))
        assert len(" ".join(text.split())) == 269

        shown = excerpt(text)

        assert shown == " ".join(["incident"] * 22) + "…"
        assert len(shown) == 197 + 1

    def test_a_text_that_fits_is_shown_whole_on_one_line(self):
        """Row 6, counter-example — the root cause on two lines, and exactly 200 characters."""
        exactly = " ".join(["incident"] * 22 + ["ab"])
        assert len(exactly) == 200

        assert excerpt(ROOT_CAUSE) == (
            "Certificate renewal and certificate deployment were two separate processes, "
            "and only the first was automated."
        )
        assert excerpt(exactly) == exactly

    def test_a_word_longer_than_the_line_is_cut_where_the_line_ends(self):
        """Row 7 — the one with no space to cut at."""
        word = "0123456789" * 25

        assert excerpt(word) == word[:200] + "…"
