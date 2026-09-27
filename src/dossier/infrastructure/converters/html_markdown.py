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

The bytes are decoded here, in the charset the page declares and otherwise as
UTF-8 (R8.32), and BeautifulSoup is handed text. Handed bytes, it guesses their
encoding with `charset-normalizer` or `chardet` if either is installed, and
MLflow installs the first, so the same file would convert differently on
machines with different extras (R8.1). A declaration is not a guess: it is the
page saying what it is.
"""

from __future__ import annotations

import codecs
from collections.abc import Mapping

from dossier.infrastructure.converters import _html

# What a reader of the page never sees, taken out before anything is written.
UNSEEN = "head, style, script, template"

# How far into the page a declared charset is looked for, as a browser looks
# (R8.32). BeautifulSoup alone would look into 2048 bytes, or 5% of a long page.
DECLARED_WITHIN = 1024


class HtmlMarkdownConverter:
    """`text/html` to the `markdown` kind."""

    id = "html-markdown"
    # Raised whenever what `convert` writes could change for the same input --
    # including when `_html` changes, or the pin on markdownify or
    # beautifulsoup4 moves (R5.4, R8.2).
    # 1.1.0: a non-breaking space at the edge of emphasis is kept (R8.21 row 6).
    # 1.2.0: a page is read in the charset it declares, not always UTF-8 (R8.32).
    version = "1.2.0"
    media_type = "text/html"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The page as markdown, UTF-8, ending in one newline.

        A page that is not in the charset it declares, or in UTF-8 when it
        declares none, fails naming this converter, and R8.6 keeps the failure
        to its one document. No encoding is guessed.
        """
        text = _decoded(payload, converter_id=self.id)
        written = _html.markdown(text, unseen=UNSEEN, image=_described).strip()
        return f"{written}\n".encode()


def _decoded(payload: bytes, *, converter_id: str) -> str:
    """The page as text: in the charset a byte-order mark names, else the one
    its `<meta>` declares, else UTF-8 (R8.32).

    BeautifulSoup finds both, as it would if it were handed the bytes, but is
    not asked to guess when neither is there. A charset with no codec fails
    naming it, and so do bytes that are not what the page says they are.
    """
    from bs4.dammit import EncodingDetector

    body, charset = EncodingDetector.strip_byte_order_mark(payload)
    charset = (
        charset
        or EncodingDetector.find_declared_encoding(body[:DECLARED_WITHIN], is_html=True)
        or "utf-8"
    )
    try:
        return body.decode(charset)
    except LookupError as error:
        raise ValueError(
            f"{converter_id} was given a page declaring the charset {charset!r}, "
            "which Python has no text codec for"
        ) from error
    except UnicodeDecodeError as error:
        named = "UTF-8" if codecs.lookup(charset).name == "utf-8" else charset
        raise ValueError(
            f"{converter_id} was given bytes that are not valid {named} "
            f"({error.reason} at byte {error.start})"
        ) from error


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
