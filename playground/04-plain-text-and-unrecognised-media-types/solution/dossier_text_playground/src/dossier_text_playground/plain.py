"""`text/plain` read as the `markdown` kind.

Almost the same converter as the one `dossier` ships for `text/markdown`, and the
"almost" is the lesson: the pair is `(media type, kind)`, so claiming
`text/markdown` says nothing about a `.txt` file. Two claims, one behaviour.

Passthrough is not nothing. The bytes are decoded as UTF-8 and re-encoded, which
is what turns "some bytes" into "text a span can be searched in" (R6.4) -- and
what makes an undecodable payload fail here, loudly, against one document, rather
than downstream with a stack trace about a byte.
"""

from __future__ import annotations

from collections.abc import Mapping


class PlainTextConverter:
    """`text/plain` to the `markdown` kind: the text as written."""

    id = "text-plain"
    # Raise this whenever output could change for the same input (R8.2, R5.4).
    # Nothing can enforce it; it is the one promise a converter author makes by
    # hand.
    version = "1.0.0"
    media_type = "text/plain"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The text as written, with nothing added and nothing reinterpreted.

        No normalising of line endings, no stripping, no BOM removal. Every one of
        those would change the artifact hash for a file nobody edited, and the
        grounding check searches this exact text.
        """
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            # One document's bytes are bad, not the configuration: R8.6's failure
            # rather than R8.5's, so the rest of the corpus still converts.
            raise ValueError(
                f"{self.id} was given bytes that are not valid UTF-8 "
                f"({error.reason} at byte {error.start})"
            ) from error
        return text.encode("utf-8")
