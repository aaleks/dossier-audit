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


class UndeclaredConverter(ValueError):
    """A converter does not declare something every converter must (R8.2).

    A `ValueError` for the same reason `NoConverter` is one: a caller can fix
    it, by correcting or not installing the package that declares it.
    """


# What a converter says about itself before dossier will use it. `version` is
# the one worth naming twice: it enters every convert key, and raising it is the
# whole mechanism R5.4 rests on.
DECLARED = ("id", "version", "media_type", "kind")


def check_declared(converter: object, *, group: str) -> None:
    """Refuse a converter that leaves any of `DECLARED` unset (R8.2 row 4).

    Checked when a converter is registered rather than when a key is composed.
    A converter with no version cannot be invalidated, so R5.4 has nothing to
    act on -- and a key built over a missing version surfaces much later as a
    cache result nobody can explain, on a machine nobody is looking at.

    Empty counts as absent: a converter declaring `version = ""` has said
    nothing, and every artifact it produced would share one key forever.
    """
    missing = [name for name in DECLARED if not getattr(converter, name, None)]
    if not missing:
        return

    identity = getattr(converter, "id", None) or type(converter).__name__
    raise UndeclaredConverter(
        f"{identity} declares no {', '.join(missing)}. Every converter declares "
        f"an id, a version, a media_type and a kind (R8.2), and a converter with "
        f"no version cannot be invalidated (R5.4). It is registered through the "
        f"{group} entry point group."
    )


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
    claimed = _claims(available)

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


def _claims(available: Sequence[Converter]) -> dict[tuple[str, str], Converter]:
    """One converter per pair, or a refusal naming the ones that disagree.

    A dict comprehension would keep the last, which is installation order on that
    machine -- and the winner's id and version are in `K_convert`, so two hosts
    with the same packages would compute different keys and different stage keys
    above them (R5.6). The registry sorts by pair, which does not break a tie
    between two converters claiming the *same* pair.

    Refusing rather than choosing, because either choice would be arbitrary and
    only one of the two claims can be right. The same converter listed twice is
    not a conflict: that is one claim made through two entry-point paths, which
    is untidy rather than ambiguous.
    """
    claimed: dict[tuple[str, str], Converter] = {}
    conflicts: list[str] = []

    for converter in available:
        pair = (converter.media_type, converter.kind)
        held = claimed.get(pair)
        if held is not None and (held.id, held.version) != (converter.id, converter.version):
            conflicts.append(
                f"({pair[0]}, {pair[1]}) is claimed by both "
                f"{held.id} {held.version} and {converter.id} {converter.version}"
            )
            continue
        claimed[pair] = converter

    if conflicts:
        raise NoConverter(
            "two converters claim the same pair, and picking either would be "
            "picking by installation order:\n  " + "\n  ".join(sorted(conflicts))
        )
    return claimed


def _claimed_pairs(available: Sequence[Converter]) -> list[str]:
    """Every installed pair, sorted, for an error message worth reading.

    Sorted because this text ends up in front of a person and, on a bad day, in a
    test assertion; an entry-point group's iteration order is not something to
    show either of them (R5.6).
    """
    return sorted(f"({c.media_type}, {c.kind})" for c in available)


# What dossier calls a file, by extension. Owned here rather than read from the
# host, which is the whole point: `mimetypes.guess_type` is seeded from
# /etc/mime.types on Linux and from HKEY_CLASSES_ROOT on Windows, so the same
# `.csv` is `text/csv` on one machine and `application/vnd.ms-excel` on another.
# That answer reaches the ledger (R2.16), picks the converter (R8.3), and the
# converter's id and version are in `K_convert` -- so a host-dependent guess forks
# every artifact hash and every stage key above it, with nothing in any diff to
# explain it (R0.4, R5.6).
#
# Deliberately small. An extension nobody has agreed on gets the honest answer
# below rather than a plausible one, and R8.5 then reports it as unclaimed.
MEDIA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".csv": "text/csv",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}

# What an unrecognised file is called. Not a guess: it says "bytes", which is
# true of anything, and lets R8.5 refuse it by name rather than hand it to a
# converter that was never meant to read it.
UNKNOWN_MEDIA_TYPE = "application/octet-stream"


def media_type_for(name: str) -> str:
    """The media type dossier assigns to a filename, on every machine (R2.16).

    Case-folded on the extension only: `INC-4821.MD` and `inc-4821.md` are the
    same kind of file, and which case a filesystem preserved is not information
    about content.
    """
    _, separator, extension = name.rpartition(".")
    if not separator:
        return UNKNOWN_MEDIA_TYPE
    return MEDIA_TYPES.get(f".{extension.casefold()}", UNKNOWN_MEDIA_TYPE)


def reported_media_type(reported: str | None, header: str | None) -> str:
    """The media type a source says a file is, made canonical (R2.16, R8.3).

    What the source records about the file wins over what the transport said
    while sending it, and either wins over a guess: a name on disk is not
    evidence about content, and neither is a missing header. Parameters are
    dropped and the type case-folded -- `application/pdf; charset=binary` and
    `Application/PDF` are one kind of file, and a converter claims the kind,
    not the transport's way of spelling it. What is returned reaches the ledger
    and every convert key, so two spellings would be two keys for one artifact.
    """
    for candidate in (reported, header):
        if candidate:
            kind = candidate.partition(";")[0].strip().casefold()
            if kind:
                return kind
    return UNKNOWN_MEDIA_TYPE
