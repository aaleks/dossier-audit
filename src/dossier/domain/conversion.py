"""Choosing the converter for a snapshot (spec 008).

The decision is a lookup on the pair `(media type, kind)`, and it is here rather
than beside the entry-point registry for the usual reason: a decision sitting in
`infrastructure/` next to the call it guards is the decay no linter finds. What
converters are *installed* is an infrastructure question; which of them answers
for a given snapshot is a rule, and R8.3 is the claim about it.

Nothing here loads a converter or runs one. `available` is passed in, so this
function can be asked the same question by a live workspace and by a test holding
three literals.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

# The kind a source gets when it declares none. `markdown` because a stage reads
# text and grounding searches converted text (R6.4) -- page images are an
# addition to that, never a replacement for it. Spec 008 records as OPEN what the
# default should be for media types beyond `application/pdf`; until that is
# settled one default answers for all of them, which is visible here rather than
# spread across call sites.
DEFAULT_KIND = "markdown"


class Converter(BaseModel):
    """One installed converter: what it is, and the pair it claims (R8.2, R8.3).

    `version` is not decoration. It enters every convert key and every provenance
    record, so raising it invalidates exactly the artifacts this converter
    produced and nothing else (R5.4).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    media_type: str
    kind: str


class NoConverter(ValueError):
    """No installed converter claims this `(media type, kind)` pair.

    A `ValueError` because a caller can fix it -- by installing a package or by
    correcting a source's `convert:` list. The application turns it into a
    stopped run (R8.5); the domain only knows that the pair is unclaimed.
    """


def select(
    *,
    media_type: str,
    kinds: Sequence[str] | None,
    available: Sequence[Converter],
) -> list[Converter]:
    """The converters that answer for one snapshot, in declaration order.

    `kinds` is the source's `convert:` list, or `None` when it declared none --
    which is the normal case for a folder source, and means the default kind for
    this media type.

    Declaration order is preserved rather than sorted: the `convert:` list is
    written by a person and the artifacts it produces should read back against
    it. Order among *equals* is never in play, because a pair matches at most one
    converter.
    """
    wanted = [DEFAULT_KIND] if kinds is None else list(kinds)
    claimed = {
        (converter.media_type, converter.kind): converter for converter in available
    }

    chosen: list[Converter] = []
    for kind in wanted:
        converter = claimed.get((media_type, kind))
        if converter is None:
            raise NoConverter(
                f"nothing converts ({media_type!r}, {kind!r}). "
                f"Claimed pairs: {_claimed_pairs(available)}. "
                "A converter is added by installing a package that declares a "
                "dossier.converters entry point."
            )
        chosen.append(converter)

    return chosen


def _claimed_pairs(available: Sequence[Converter]) -> list[str]:
    """Every installed pair, sorted, for an error message worth reading.

    Sorted because this text ends up in front of a person and, on a bad day, in a
    test assertion; an entry-point group's iteration order is not something to
    show either of them (R5.6).
    """
    return sorted(f"({c.media_type}, {c.kind})" for c in available)
