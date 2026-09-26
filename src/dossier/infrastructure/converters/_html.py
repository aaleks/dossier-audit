"""HTML as markdown a span is searched in (spec 008, R8.20, R8.21).

Shared by the converters whose input is HTML: a Confluence page's rendered body,
and an HTML file someone exported. Each says what a reader of its HTML never
sees and how an image is written. Everything else is decided once, here.

[`markdownify`](https://github.com/matthewwithanm/python-markdownify) writes the
markdown, over a tree BeautifulSoup builds with the standard library's parser.
Both are pinned, and a change to either, or to the options below, changes the
artifacts of every converter using this module: each of their versions moves
with it (R5.4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import unquote, urlsplit

# The choices R8.17 made for wiki markup, for the same reason: the artifact is
# text a span is searched in, not markdown for a renderer. Nothing is escaped,
# so `lb_acq_01` and `3*2` are written as they stand.
OPTIONS: Mapping[str, object] = {
    "heading_style": "atx",
    "bullets": "-",
    "escape_asterisks": False,
    "escape_underscores": False,
    "escape_misc": False,
}

# A non-breaking space, written as an escape because the character is invisible.
NBSP = "\u00a0"

# How an `<img>` is written, from its attributes; `None` keeps markdownify's own.
Image = Callable[[Mapping[str, str]], str]


def markdown(html: str, *, unseen: str, image: Image | None = None) -> str:
    """`html` as markdown, without the elements `unseen` selects.

    Text, never bytes: handed bytes, BeautifulSoup guesses their encoding with
    whichever detector is installed, and a converter's output may depend on its
    input alone (R8.1). The caller decodes.
    """
    from bs4 import BeautifulSoup

    tree = BeautifulSoup(html, "html.parser")
    for element in tree.select(unseen):
        element.decompose()
    # A non-breaking space as a space. markdownify strips the whitespace at the
    # edges of bold and emphasis and puts back only an ASCII space, so
    # `<strong>Released:&nbsp;</strong>0.10.0.0` lost the space a reader sees
    # and a quote copied from the page did not ground (R8.20 row 7). The span
    # check folds one into the other anyway (R6.17), so nothing is lost here.
    for text in tree.find_all(string=lambda value: NBSP in value):
        text.replace_with(text.replace(NBSP, " "))
    return _writer(image)(**OPTIONS).convert_soup(tree)


def file_name(src: str) -> str:
    """The name of the file `src` points at: the last segment of its path, unquoted."""
    return unquote(urlsplit(src).path.rsplit("/", 1)[-1])


def _writer(image: Image | None):
    """markdownify's converter, writing an image as `image` says.

    Built on first use so that importing a converter does not import the
    library, as the other converters defer theirs.
    """
    from markdownify import MarkdownConverter

    if image is None:
        return MarkdownConverter

    class Writer(MarkdownConverter):
        def convert_img(self, el, text, parent_tags):
            return image({key: str(value) for key, value in el.attrs.items()})

    return Writer
