"""An HTML file someone exported, read as the page a reader sees (spec 008, R8.21).

A wiki page saved as HTML is one of the files a Jira issue or a Confluence page
most often carries, and nothing claimed `(text/html, markdown)`, so one such
attachment stopped its whole source (R8.5).

It is read with the reader `confluence-page-markdown` uses (`_html`), so the
choices are the same: nothing escaped, and what a reader never sees taken out
first. In a file, that is the whole `<head>` -- its `<title>` would otherwise be
written as a line of its own, above the heading that repeats it -- and every
`<style>`, `<script>` and `<template>`. An image is its alt text and the name of
its file (R8.22), never its URL, and never the base64 an export inlines.

The bytes are decoded as UTF-8 here, and BeautifulSoup is handed text. Handed
bytes, it guesses their encoding with `charset-normalizer` or `chardet` if either
is installed, and MLflow installs the first, so the same file would convert
differently on machines with different extras (R8.1).
"""

from __future__ import annotations

from collections.abc import Mapping

from dossier.infrastructure.converters import _html
from dossier.infrastructure.converters._decode import decode_utf8

# What a reader of the page never sees, taken out before anything is written.
UNSEEN = "head, style, script, template"


class HtmlMarkdownConverter:
    """`text/html` to the `markdown` kind."""

    id = "html-markdown"
    # Raised whenever what `convert` writes could change for the same input --
    # including when `_html` changes, or the pin on markdownify or
    # beautifulsoup4 moves (R5.4, R8.2).
    version = "1.0.0"
    media_type = "text/html"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The page as markdown, UTF-8, ending in one newline.

        A file that is not UTF-8 fails naming this converter, and R8.6 keeps
        the failure to its one document. No encoding is guessed.
        """
        text = decode_utf8(payload, converter_id=self.id).decode("utf-8")
        written = _html.markdown(text, unseen=UNSEEN, image=_described).strip()
        return f"{written}\n".encode()


def _described(attributes: Mapping[str, str]) -> str:
    """An image as its alt text and the name of its file (R8.22).

    The alt text is what a reader who cannot see the image is told; the name ties
    it to its file. A `data:` URI names no file and is not written at all: an
    export inlining its images would otherwise put their base64 into the note.
    With neither alt text nor a file, nothing is written, and no words are made
    up for it.
    """
    src = attributes.get("src", "").strip()
    name = "" if src.lower().startswith("data:") else _html.file_name(src)
    label = attributes.get("alt", "").strip() or name
    return f"![{label}]({name})" if label else ""
