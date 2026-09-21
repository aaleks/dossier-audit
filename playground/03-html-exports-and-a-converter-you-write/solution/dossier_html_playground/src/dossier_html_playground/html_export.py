"""`text/html` read as the `markdown` kind: the text a stage will see.

The whole contract is R8.1: the artifact is a pure function of the snapshot bytes
and the declared options. No clock, no locale, no file outside the input, no
network. Everything here reads `payload` and nothing else, which is what makes
`K_convert` -- snapshot hash, converter id, version, options -- a true statement
about the bytes it produced.

`version` is the one promise no test can enforce: raise it whenever output could
change for the same input (R8.2, R5.4). For this converter that includes every
decision below about what becomes a heading and what is dropped -- the artifact
is generated here, not passed through, so its shape is this module's answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from html.parser import HTMLParser

# Tags whose text is markup machinery rather than document content. A wiki export
# carries both, and a stage grounding a span in the artifact (R6.4) should not be
# able to quote a CSS rule back as evidence.
DROPPED = frozenset({"script", "style", "head", "title", "noscript"})

# Tags that end the block being collected. Everything else is inline, so a
# `<strong>` inside a sentence does not split it in two.
BLOCKS = frozenset({"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br"})

HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


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

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in DROPPED:
            self._dropping += 1
            return
        if tag in BLOCKS:
            self._flush()
            self._prefix = (
                f"{HEADINGS[tag]} " if tag in HEADINGS else ("- " if tag == "li" else "")
            )

    def handle_endtag(self, tag: str) -> None:
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
        if not self._dropping:
            self._text.append(data)

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


class HtmlMarkdownConverter:
    """An exported HTML page's text, one markdown block per block element."""

    id = "html-markdown"
    version = "0.1.0"
    media_type = "text/html"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The page's text as markdown, as UTF-8.

        A page carrying no text -- a dashboard exported as one `<img>` -- converts
        to an empty artifact rather than failing. That is the honest answer: the
        bytes really do carry no text, and it is exactly what `dossier convert`
        exists to show before a single model call is made. A stage that then finds
        nothing to ground a span in reports an ungrounded field (R6.4), which is
        the right outcome for a page nobody can read as text.

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
