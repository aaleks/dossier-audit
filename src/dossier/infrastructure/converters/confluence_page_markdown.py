"""A Confluence page, read as the note a person reads (spec 008, R8.19, R8.20).

The Confluence connector holds a page as the JSON Confluence sends for it
rendered for export, labelled as a Confluence page rather than as JSON (R1.17),
and this is the converter that claims that label. Which parts are the note, and
in which order, is the domain's decision (`dossier.domain.confluence_page.note`).
What is decided here is how the rendered body becomes markdown.

[`markdownify`](https://github.com/matthewwithanm/python-markdownify) writes it,
over a tree BeautifulSoup builds with the standard library's parser. The choices
are the ones `jira-issue-markdown` made, for the same reason: the artifact is
text a span is searched in, not markdown for a renderer (R8.20).

* **Nothing is escaped**, so `lb_acq_01` and `3*2` are written as they stand.
* **What a reader does not see is taken out first**: the content of `<style>`
  and `<script>`, and the table of contents macro. The macro repeats the page's
  headings, and its class name holds the time it was rendered.
* **An image is written as the file it shows.** The file is its own document
  (R1.18). The server's URL for it holds the page's title and moves when the
  page is renamed.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import unquote, urlsplit

from dossier.domain.confluence_page import note
from dossier.domain.conversion import CONFLUENCE_PAGE

# What a reader of the page never sees, taken out before anything is written.
UNSEEN = "div.toc-macro, style, script"


class ConfluencePageMarkdownConverter:
    """A Confluence page to the `markdown` kind."""

    id = "confluence-page-markdown"
    # Raised whenever what `convert` writes could change for the same payload --
    # including when the pin on markdownify or beautifulsoup4 moves, since the
    # libraries' versions are not in the key and this one is (R5.4, R8.2).
    version = "1.0.0"
    media_type = CONFLUENCE_PAGE
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The page as a note, UTF-8, ending in one newline.

        `options` is accepted and unused, as the shipped converters accept it.
        A payload that is not a rendered page fails naming this converter, and
        R8.6 keeps the failure to its one document.
        """
        try:
            written = note(payload, markup=markdown)
        except ValueError as error:
            raise ValueError(f"{self.id}: {error}") from None
        return written.encode("utf-8")


def markdown(html: str) -> str:
    """A page's rendered body as markdown, unescaped, without what a reader does not see."""
    from bs4 import BeautifulSoup

    tree = BeautifulSoup(html, "html.parser")
    for unseen in tree.select(UNSEEN):
        unseen.decompose()
    return _writer()(
        heading_style="atx",
        bullets="-",
        escape_asterisks=False,
        escape_underscores=False,
        escape_misc=False,
    ).convert_soup(tree)


def _writer():
    """markdownify's converter, writing an image as the name of its file (R8.20 row 4).

    Built on first use so that importing this module does not import the
    library, as the other converters defer theirs.
    """
    from markdownify import MarkdownConverter

    class Writer(MarkdownConverter):
        def convert_img(self, el, text, parent_tags):
            name = unquote(urlsplit(el.get("src") or "").path.rsplit("/", 1)[-1])
            return f"![{name}]({name})" if name else ""

    return Writer
