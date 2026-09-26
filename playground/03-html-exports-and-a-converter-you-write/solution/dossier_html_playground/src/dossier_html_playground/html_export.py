"""`text/html` read as the `markdown` kind, the way this workspace wants its wiki.

`dossier` ships `html-markdown`, and it answers this pair by default (R8.21).
This converter exists for the one thing that one keeps on purpose: the
breadcrumb. This wiki's exporter writes where a page lives as the first line of
every page, in a `<div class="breadcrumb">`. Move a page to another space and its
note changes by that one line, so every step reads it again and asks a model
about a document whose content did not change. The shipped converter keeps the
trail because a reader sees it, and because telling navigation from content by
class name is a heuristic -- the one `trafilatura` was rejected for (R8.21
row 1). A workspace that knows its exporter can make that call. `dossier`,
reading every exporter there is, cannot.

The whole contract is R8.1: the artifact is a pure function of the snapshot
bytes and the declared options. No clock, no locale, no file outside the input,
no network. Everything here reads `payload` and nothing else, which is what makes
`K_convert` -- snapshot hash, converter id, version, options -- a true statement
about the bytes it produced.

`version` is the one promise no test can enforce: raise it whenever output could
change for the same input (R8.2, R5.4). For this converter that includes every
decision below about what becomes a heading and what is dropped, and the
standard library's `html.parser`, which is whichever interpreter you run.
"""

from __future__ import annotations

from collections.abc import Mapping
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

# Tags whose text is markup machinery rather than document content. A wiki export
# carries both, and a stage grounding a span in the artifact (R6.4) should not be
# able to quote a CSS rule back as evidence.
DROPPED = frozenset({"script", "style", "head", "title", "noscript", "template"})

# What this wiki's exporter wraps around every page, by class. The decision this
# package was written for, and a fact about one exporter: another wiki's trail is
# kept, which is the price of deciding by class name.
CHROME = frozenset({"breadcrumb"})

# Tags that end the block being collected. Everything else is inline, so a
# `<strong>` inside a sentence does not split it in two.
BLOCKS = frozenset({"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br"})

HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}

# Elements that never have an end tag. One of these carrying a chrome class must
# not start a skip that no end tag would ever close.
VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"})


class _Reader(HTMLParser):
    """Collects one markdown block per block-level element, in document order.

    A parser rather than a regular expression: an attribute holding `<` or a
    comment holding a tag name are both ordinary in an exported page, and a
    pattern that got either wrong would produce an artifact nobody could ground a
    span in and no error anywhere.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._text: list[str] = []
        self._prefix = ""
        self._dropping = 0
        # The chrome element being skipped, and how deep inside it the parser is,
        # so a `<div>` nested in the breadcrumb does not end the skip early.
        self._chrome_tag = ""
        self._chrome_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._chrome_depth:
            if tag == self._chrome_tag:
                self._chrome_depth += 1
            return
        if tag in DROPPED:
            self._dropping += 1
            return
        attributes = {name: value or "" for name, value in attrs}
        if tag not in VOID and CHROME & set(attributes.get("class", "").split()):
            self._flush()
            self._chrome_tag, self._chrome_depth = tag, 1
            return
        if tag in BLOCKS:
            self._flush()
            self._prefix = (
                f"{HEADINGS[tag]} " if tag in HEADINGS else ("- " if tag == "li" else "")
            )
        if tag == "img" and not self._dropping:
            self._text.append(f" {_image(attributes)} ")

    def handle_endtag(self, tag: str) -> None:
        if self._chrome_depth:
            if tag == self._chrome_tag:
                self._chrome_depth -= 1
            return
        if tag in DROPPED:
            # Never below zero: an export with a stray `</script>` is untidy
            # rather than unreadable, and dropping the rest of the document over
            # it would be a converter deciding a document is bad (R8.6) when it
            # is merely sloppy.
            self._dropping = max(0, self._dropping - 1)
            return
        if tag in BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._dropping and not self._chrome_depth:
            self._text.append(data)

    def close(self) -> None:
        super().close()
        # Text after the last block element -- an `<img>` straight inside
        # `<body>` -- is a block too, and would otherwise be lost.
        self._flush()

    def _flush(self) -> None:
        # `split()` on no argument collapses every run of whitespace to one
        # space, which is what makes the artifact independent of how the
        # exporter happened to indent its markup: two exports of the same page
        # with different wrapping must hash the same (R5.6).
        text = " ".join("".join(self._text).split())
        self._text = []
        prefix, self._prefix = self._prefix, ""
        if text:
            self.blocks.append(f"{prefix}{text}")


def _image(attributes: Mapping[str, str]) -> str:
    """An image as its alt text and the name of its file, as `html-markdown` writes one.

    Added in 0.2.0, which is why the version moved. Before it, a page whose body
    is one `<img>` converted to nothing: an empty note, which a step still reads.
    R6.21 skips a document holding *no* artifact of the kind a step reads, and an
    empty one is still an artifact, so a model was asked about a document with
    nothing in it. The name of the file is a fact the page states, and alt text
    is what a reader who cannot see the picture is told. Neither is made up. A
    `data:` URI names no file, and none of its base64 is written (R8.22).
    """
    src = attributes.get("src", "").strip()
    name = ""
    if not src.lower().startswith("data:"):
        # The last segment of the path, unquoted: no host, and no query string.
        name = unquote(urlsplit(src).path.rsplit("/", 1)[-1])
    label = attributes.get("alt", "").strip() or name
    return f"![{label}]({name})" if label else ""


class HtmlMarkdownConverter:
    """An exported wiki page's text, one markdown block per block element."""

    id = "play-html-markdown"
    # 0.1.0: the text of the page, without its breadcrumb.
    # 0.2.0: an image is written as its alt text and the name of its file.
    version = "0.2.0"
    media_type = "text/html"
    kind = "markdown"
    # It claims the pair `html-markdown` already answers, so it answers only in a
    # workspace whose sources.yaml names it (R8.13). Installing it then changes
    # nothing anywhere else, the repository's own test suite included.
    opt_in = True

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The page's text as markdown, as UTF-8.

        `options` is accepted and unused: this converter has none. The argument
        stays in the signature because every converter is called the same way, and
        options are part of the key -- so an option nobody reads still produces
        its own cache entry rather than quietly sharing one.
        """
        try:
            # Strict rather than `errors="replace"`: an export that is not UTF-8
            # is one document's bytes being wrong, which is R8.6's failure and
            # not R8.5's. Substituting replacement characters would convert it
            # successfully into text nobody wrote.
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"{self.id} could not decode this export as UTF-8: {error}"
            ) from error

        reader = _Reader()
        try:
            reader.feed(text)
            reader.close()
        except Exception as error:
            raise ValueError(f"{self.id} could not read this export: {error}") from error

        return "\n\n".join(reader.blocks).encode("utf-8")
