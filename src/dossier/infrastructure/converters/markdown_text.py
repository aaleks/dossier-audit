"""Markdown in, markdown out (spec 008).

The simplest converter there is, and not a placeholder: a folder of `.md` notes
is a real source, and this is what makes one readable by a stage. It also fixes
the shape every other converter follows.

Passthrough is not quite nothing. The bytes are decoded as UTF-8 and re-encoded,
which is what turns "some bytes" into "text a span can be searched in" (R6.4) and
what makes an undecodable payload fail here -- loudly, once, against one document
-- rather than somewhere downstream with a stack trace about a byte.
"""

from __future__ import annotations

from collections.abc import Mapping


class MarkdownTextConverter:
    """`text/markdown` to the `markdown` kind."""

    id = "markdown-text"
    # Raise this whenever output could change for the same input. Nothing can
    # enforce that; it is the one promise a converter author makes by hand, and
    # R5.4 is what it buys.
    version = "1.0.0"
    media_type = "text/markdown"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The text as written, with nothing added and nothing reinterpreted.

        No normalising of line endings, no stripping, no BOM removal. Every one
        of those would change the artifact hash for a file nobody edited, and the
        grounding check searches this exact text (R6.4).

        `options` is accepted and unused: this converter has none. Taking the
        argument keeps the interface uniform, and a caller passing options that
        do nothing is not silently wrong -- the options are in the key, so an
        option nobody reads still produces its own cache entry.
        """
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"{self.id} was given bytes that are not valid UTF-8 "
                f"({error.reason} at byte {error.start})"
            ) from error
        return text.encode("utf-8")
