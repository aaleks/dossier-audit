"""R8.20 — a page's body is written as markdown, unescaped, and without what a
reader does not see.

`confluence-page-markdown` hands the rendered body to `markdownify`, with the
choices R8.17 made for wiki markup: nothing backslash-escaped, `-` bullets, `#`
headings. Before it does, the table of contents and anything inside `<style>` or
`<script>` are taken out. An embedded image is written as the name of the file
it shows, which is its own document (R1.18).

What the library does with each construct is the library's to prove. These rows
are the boundary: which HTML reaches it, and what this converter changes.
"""

from __future__ import annotations

import json
from pathlib import Path

from dossier.infrastructure.converters.confluence_page_markdown import (
    ConfluencePageMarkdownConverter,
)

PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "confluence" / "81920114.json"


def converted(body: str | None = None) -> str:
    """`OPS-114`, with its body replaced where given, as the converter writes it."""
    page = json.loads(PAGE.read_bytes())
    if body is not None:
        page["body"]["export_view"]["value"] = body
    payload = json.dumps(page).encode("utf-8")
    return ConfluencePageMarkdownConverter().convert(payload, {}).decode("utf-8")


class TestAPagesBodyIsWrittenAsMarkdown:
    """R8.20 — markdown a span is searched in, holding only what a reader sees."""

    def test_a_heading_and_a_list_become_markdown(self):
        """Row 1: the one where the procedure's first step is a list item."""
        written = converted("<h2>Escalation</h2><ul><li>Page the incident commander</li></ul>")

        assert written.index("## Escalation\n") < written.index(
            "- Page the incident commander\n"
        )

    def test_a_link_becomes_a_markdown_link(self):
        """Row 2: the one where the page links the rota."""
        written = converted('<p><a href="https://status.example/rota">the rota</a></p>')

        assert "[the rota](https://status.example/rota)" in written

    def test_nothing_is_backslash_escaped(self):
        """Row 3: the one where a model quotes `lb_acq_01` and `3*2` as they stand."""
        written = converted("<p>pool lb_acq_01 held 3*2 connections</p>")

        assert "pool lb_acq_01 held 3*2 connections" in written
        assert "\\" not in written

    def test_an_image_is_written_as_the_file_it_shows(self):
        """Row 4: the one where the server's download URL is not kept."""
        written = converted()

        assert "![escalation-matrix.png](escalation-matrix.png)" in written
        assert "download/attachments" not in written
        assert "embedded-page" not in written

    def test_the_table_of_contents_and_its_style_are_not_in_the_note(self):
        """Counter-example, row 5: the one where each heading is there once, where it stands."""
        written = converted()

        assert "rbtoc" not in written and "padding" not in written
        assert "OPS114Incidentescalationprocedure" not in written
        assert written.count("Escalation") == 1
        assert written.count("Out of hours") == 2  # its heading, and the sentence under it

    def test_text_inside_an_expand_macro_is_kept(self):
        """Counter-example, row 6: the one where a reader clicks to read it, and can."""
        written = converted()

        assert "Out of hours, the duty manager approves any customer notice." in written

    def test_a_script_is_not_in_the_note(self):
        """Row 5's reason, for `<script>`: the one where the text is machinery."""
        written = converted("<p>Before.</p><script>var rota = 'on call';</script><p>After.</p>")

        assert "var rota" not in written
        assert "Before." in written and "After." in written

    def test_a_non_breaking_space_at_the_edge_of_bold_is_kept(self):
        """Row 7: the one where `Released: 0.10.0.0` is copied from the page."""
        written = converted("<p><strong>Released:&nbsp;</strong>0.10.0.0</p>")

        assert "**Released:** 0.10.0.0" in written
