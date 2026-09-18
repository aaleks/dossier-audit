"""Plain text in, text out (spec 008).

`text/plain` has been in `MEDIA_TYPES` since that table was written, and nothing
claimed it. A folder holding one `.txt` note beside its `.md` files therefore
stopped the whole run on an unclaimed pair (R8.5) -- correct behaviour for a
media type dossier cannot read, and the wrong answer for one it obviously can.

Separate from `markdown-text` rather than a second media type on it: a converter
claims exactly one pair (R8.3), and registration is what makes that claim. The
two share their body, not their identity -- and their versions move
independently, which is the whole of R5.4.
"""

from __future__ import annotations

from collections.abc import Mapping

from dossier.infrastructure.converters._decode import decode_utf8


class TextPlainConverter:
    """`text/plain` to the `markdown` kind."""

    id = "text-plain"
    # Raise this whenever output could change for the same input. Nothing can
    # enforce that; it is the one promise a converter author makes by hand.
    version = "1.0.0"
    media_type = "text/plain"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The text as written.

        Plain text *is* markdown for this purpose: a stage reads text and a span
        is searched in it (R6.4). Wrapping it in a fence or escaping its markup
        would change bytes a person wrote, for the benefit of a renderer nothing
        here has.

        `options` is accepted and unused: this converter has none. Taking the
        argument keeps the interface uniform, and an option nobody reads still
        produces its own cache entry because options are in the key (R8.1).
        """
        return decode_utf8(payload, converter_id=self.id)
