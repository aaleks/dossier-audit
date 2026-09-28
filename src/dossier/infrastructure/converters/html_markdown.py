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

A page a website serves carries the site around it: a header, menus, a sidebar,
a footer, the same on every page. A page that says where its content is, with
one `<main>`, is written as that element, without the `<nav>` inside it (R8.33).
Nothing is chosen by class name or by how much text a block holds; a page that
says nothing is written whole.

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

# Where a page says its content is (R8.33): HTML's element, and ARIA's role for
# it. And what is taken from inside it: a theme's menus and a page's table of
# contents sit there as often as not.
MAIN = 'main, [role="main"]'
NAVIGATION = 'nav, [role="navigation"]'

# How far into the page a declared charset is looked for, as a browser looks
# (R8.32). BeautifulSoup alone would look into 2048 bytes, or 5% of a long page.
DECLARED_WITHIN = 1024

# Declared names a browser reads otherwise than Python does, by the WHATWG
# Encoding Standard's table (https://encoding.spec.whatwg.org/#names-and-labels),
# and what each is read as (R8.32). Every other name is read as Python reads it.
#
# Every label the Standard gives windows-1252. Python reads `iso-8859-1` as
# Latin-1, where `0x96` is a control character and not `–`, and does not know
# `iso88591` or `x-cp1252` at all.
WINDOWS_1252 = (
    "ansi_x3.4-1968",
    "ascii",
    "cp1252",
    "cp819",
    "csisolatin1",
    "ibm819",
    "iso-8859-1",
    "iso-ir-100",
    "iso8859-1",
    "iso88591",
    "iso_8859-1",
    "iso_8859-1:1987",
    "l1",
    "latin1",
    "us-ascii",
    "windows-1252",
    "x-cp1252",
)
# Every label it gives UTF-16LE or UTF-16BE. A declaration BeautifulSoup could
# read as ASCII was not written two bytes to a character, so a browser's prescan
# reads the page as UTF-8. A byte-order mark is read before any declaration, so
# a page that really is UTF-16 never gets here.
UTF_16 = (
    "csunicode",
    "iso-10646-ucs-2",
    "ucs-2",
    "unicode",
    "unicodefeff",
    "unicodefffe",
    "utf-16",
    "utf-16be",
    "utf-16le",
)
AS_A_BROWSER_READS: Mapping[str, str] = {
    **dict.fromkeys(WINDOWS_1252, "windows-1252"),
    **dict.fromkeys(UTF_16, "utf-8"),
}


class HtmlMarkdownConverter:
    """`text/html` to the `markdown` kind."""

    id = "html-markdown"
    # Raised whenever what `convert` writes could change for the same input --
    # including when `_html` changes, or the pin on markdownify or
    # beautifulsoup4 moves (R5.4, R8.2).
    # 1.1.0: a non-breaking space at the edge of emphasis is kept (R8.21 row 6).
    # 1.2.0: a page is read in the charset it declares, as a browser reads the
    # name, and not always as UTF-8 (R8.32).
    # 1.3.0: a page that declares one `<main>` is written as that element,
    # without the `<nav>` in it (R8.33).
    version = "1.3.0"
    media_type = "text/html"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The page as markdown, UTF-8, ending in one newline.

        A page that is not in the charset it declares, or in UTF-8 when it
        declares none, fails naming this converter, and R8.6 keeps the failure
        to its one document. No encoding is guessed.
        """
        text = _decoded(payload, converter_id=self.id)
        written = _html.markdown(text, unseen=UNSEEN, image=_described, content=_declared)
        return f"{written.strip()}\n".encode()


def _declared(tree):
    """The page's `<main>` without its `<nav>`, when it declares exactly one (R8.33).

    Otherwise the whole page, as R8.21 reads it: a page declaring none has not
    said where its content is, and one declaring two has said it twice. Nothing
    is chosen by class, id or how much text a block holds.
    """
    mains = tree.select(MAIN)
    if len(mains) != 1:
        return tree
    (main,) = mains
    for element in main.select(NAVIGATION):
        element.decompose()
    return main


def _decoded(payload: bytes, *, converter_id: str) -> str:
    """The page as text: in the charset a byte-order mark names, else the one
    it declares, read as a browser reads its name, else UTF-8 (R8.32).

    BeautifulSoup finds the mark and the declaration -- a `<meta>`, or an XML
    declaration at the start -- as it would if it were handed the bytes, but is
    not asked to guess when neither is there. A charset with no codec fails
    naming it, and so do bytes that are not what the page says they are.
    """
    from bs4.dammit import EncodingDetector

    body, charset = EncodingDetector.strip_byte_order_mark(payload)
    if charset is None:
        declared = EncodingDetector.find_declared_encoding(body[:DECLARED_WITHIN], is_html=True)
        charset = AS_A_BROWSER_READS.get(declared, declared) if declared else "utf-8"
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
