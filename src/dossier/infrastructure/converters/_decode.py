"""Turning bytes into text a span can be searched in (spec 008).

Shared by every converter whose input is already text. Passthrough is not quite
nothing: the decode is what makes an undecodable payload fail here -- loudly,
once, against one document (R8.6) -- rather than downstream with a stack trace
about a byte, or worse, as replacement characters that a span would then be
grounded against (R6.4).
"""

from __future__ import annotations


def decode_utf8(payload: bytes, *, converter_id: str) -> bytes:
    """The text as written, with nothing added and nothing reinterpreted.

    No normalising of line endings, no stripping, no BOM removal. Every one of
    those would change the artifact hash for a file nobody edited, and the
    grounding check searches this exact text (R6.4).

    `ValueError` rather than letting `UnicodeDecodeError` through: a caller can
    fix this, by fixing the file or by pointing the source somewhere else, and
    R8.6 reports it against the one document it belongs to.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(
            f"{converter_id} was given bytes that are not valid UTF-8 "
            f"({error.reason} at byte {error.start})"
        ) from error
    return text.encode("utf-8")
