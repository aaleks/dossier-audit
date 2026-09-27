"""R8.21 — `html-markdown` converts an HTML file to markdown of what a reader sees
on the page, unescaped.

The page's body, written with the reader `confluence-page-markdown` uses (R8.20).
The whole `<head>` is taken out, and so are `<style>`, `<script>` and
`<template>` wherever they are. The bytes are decoded here, as UTF-8 unless the
page declares its charset (R8.32), before BeautifulSoup sees them: given bytes,
it guesses the encoding with whichever detector is installed, and a converter's
output may not depend on that (R8.1).

`PLAY-4001` is `tests/fixtures/documents/exports/PLAY-4001-payment-retries.html`,
a wiki page saved as HTML.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.infrastructure.converters.html_markdown import HtmlMarkdownConverter

EXPORT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "documents"
    / "exports"
    / "PLAY-4001-payment-retries.html"
)


def converted(html: str | bytes) -> str:
    payload = html.encode("utf-8") if isinstance(html, str) else html
    return HtmlMarkdownConverter().convert(payload, {}).decode("utf-8")


class TestAnHtmlFileConvertsToWhatAReaderSees:
    """R8.21 — the body a reader sees, as markdown a span is searched in."""

    def test_an_exported_page_converts_to_its_body(self):
        """Example 1: the one where a wiki page was saved as HTML."""
        written = converted(EXPORT.read_bytes())

        assert "Spaces / Site Reliability / Postmortems / 2026 / PLAY-4001" in written
        assert "# PLAY-4001 — Duplicate payment retries after a queue redelivery\n" in written
        assert "**Severity:** major" in written
        assert "## Timeline\n" in written
        assert "- 2026-04-17 21:06 UTC" in written

    def test_the_title_is_there_once_and_the_css_not_at_all(self):
        """Example 1, continued: the one where the `<head>` is what nobody reads."""
        written = converted(EXPORT.read_bytes())

        assert written.count("Duplicate payment retries after a queue redelivery") == 1
        assert "font-family" not in written and "breadcrumb {" not in written

    def test_nothing_is_backslash_escaped(self):
        """Example 3: the one where a model quotes `lb_acq_01` and `3*2` as they stand."""
        written = converted("<p>pool lb_acq_01 held 3*2 connections</p>")

        assert "pool lb_acq_01 held 3*2 connections" in written
        assert "\\" not in written

    def test_a_page_in_windows_1252_fails_naming_utf8(self):
        """Counter-example, row 4: the one where the encoding would have to be guessed."""
        payload = "<p>Résolu le 2026-04-18</p>".encode("cp1252")

        with pytest.raises(ValueError) as error:
            converted(payload)

        assert "html-markdown" in str(error.value) and "UTF-8" in str(error.value)

    def test_a_script_in_the_body_is_not_in_the_note(self):
        """Counter-example, row 5: the one where the text is machinery."""
        written = converted(
            "<body><p>Before.</p><script>var rota = 'on call';</script><p>After.</p></body>"
        )

        assert "var rota" not in written
        assert "Before." in written and "After." in written

    def test_a_template_is_not_in_the_note(self):
        """Row 5's reason, for `<template>`: markup a browser never shows."""
        written = converted("<p>Shown.</p><template><p>Never rendered.</p></template>")

        assert "Never rendered." not in written
        assert "Shown." in written

    def test_it_claims_html_as_markdown(self):
        """The pair it answers, which nothing answered before (R8.5)."""
        converter = HtmlMarkdownConverter()

        assert (converter.id, converter.media_type, converter.kind) == (
            "html-markdown",
            "text/html",
            "markdown",
        )

    def test_a_non_breaking_space_at_the_edge_of_emphasis_is_kept(self):
        """Row 6: the one where the space a reader sees stays between the words."""
        written = converted("<p>Released<em>&nbsp;now</em></p>")

        assert "Released *now*" in written
