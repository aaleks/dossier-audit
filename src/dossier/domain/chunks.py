"""Where a document is cut for the index, and what each piece is called (spec 018).

The `headings` chunker is a pure decision: a document's converted text in, its
chunks out. Its name, version and settings are part of every chunk's id
(R18.2), so a chunker that comes to cut differently re-chunks rather than
mixing old pieces and new ones in one index. Nothing here embeds a chunk or
writes it anywhere.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from dossier.domain.hashing import content_hash, normalised_text

HEADINGS = "headings"
# Moves whenever `heading_chunks` would cut the same text differently. The id
# of every chunk it cut carries it, so an index built by the old cut is
# rebuilt rather than left holding pieces the new one would never produce.
HEADINGS_VERSION = 1
HEADINGS_CHUNKER = f"{HEADINGS}@{HEADINGS_VERSION}"

# A closing run of `#` is dropped only after a space, as CommonMark reads it:
# `## Why C#` is a heading about C#, and `## Impact ##` one about the impact.
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_FENCE = "```"

# Coarsest first: a piece is cut at the widest break that brings it under
# `max_chars`, and joined back with what that break was (R18.1).
_BREAKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\n\s*\n"), "\n\n"),  # a paragraph
    (re.compile(r"(?<=[.!?])\s+"), " "),  # a sentence's end
    (re.compile(r"\s+"), " "),  # a space
)


@dataclass(frozen=True)
class Chunk:
    """One piece of a document, under the headings above it (R18.1).

    `index` counts across the whole document, not within a section: it is the
    chunk's position in its chunk id (R18.2).
    """

    index: int
    heading_path: tuple[str, ...]
    text: str


def heading_chunks(text: str, *, max_chars: int) -> list[Chunk]:
    """`text` cut at its headings, each section into pieces of at most `max_chars` (R18.1).

    A section with nothing in it is no chunk: its vector would be of its
    headings alone, and would match a search for them better than the section
    that says something. Text before the first heading has the path `()`; a
    document's title is its key, and the index carries that apart.
    """
    if max_chars < 1:
        raise ValueError(f"max_chars must be at least 1, not {max_chars}")
    chunks: list[Chunk] = []
    for path, section in _sections(text):
        for piece in _cut(section, max_chars, _BREAKS):
            chunks.append(Chunk(index=len(chunks), heading_path=path, text=piece))
    return chunks


def _sections(text: str) -> Iterator[tuple[tuple[str, ...], str]]:
    """Each section with text in it: its heading path, and its text without the heading.

    Line endings are normalised first, so a note checked out with CRLF is cut
    into the same chunks, with the same ids, as one with LF (R0.4). A `#` line
    inside a fenced code block is a shell prompt or a comment someone pasted,
    not a section of the document.
    """
    open_headings: list[tuple[int, str]] = []
    lines: list[str] = []
    fenced = False
    for line in normalised_text(text).split("\n"):
        if line.startswith(_FENCE):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading is None:
            lines.append(line)
            continue
        yield from _section(open_headings, lines)
        level = len(heading.group(1))
        # A heading closes every heading at its own level or deeper, and only
        # those: a `##` after a `###` is a sibling of the `###`'s parent.
        while open_headings and open_headings[-1][0] >= level:
            open_headings.pop()
        open_headings.append((level, heading.group(2)))
        lines = []
    yield from _section(open_headings, lines)


def _section(
    open_headings: Sequence[tuple[int, str]], lines: Sequence[str]
) -> Iterator[tuple[tuple[str, ...], str]]:
    section = "\n".join(lines).strip()
    if section:
        yield tuple(title for _, title in open_headings), section


def _cut(text: str, max_chars: int, breaks: Sequence[tuple[re.Pattern[str], str]]) -> list[str]:
    """`text` as pieces of at most `max_chars`, cut at the coarsest break that fits.

    Whole parts are packed greedily, so a piece is as full as the parts allow.
    A part too long to be packed is cut at the next finer break on its own, and
    never shares a piece with its neighbours: its pieces are already as full as
    its own breaks allow. A word longer than `max_chars` has no break left in
    it, and is cut every `max_chars` characters, because no piece is ever
    longer than that.
    """
    if len(text) <= max_chars:
        return [text]
    if not breaks:
        return [text[start : start + max_chars] for start in range(0, len(text), max_chars)]
    (pattern, joiner), finer = breaks[0], breaks[1:]
    pieces: list[str] = []
    piece = ""
    # `text` is stripped, and every break is a run of whitespace taken whole,
    # so no part between two breaks is empty once stripped.
    for part in (part.strip() for part in pattern.split(text)):
        if len(part) > max_chars:
            pieces += [piece] if piece else []
            pieces += _cut(part, max_chars, finer)
            piece = ""
        elif not piece:
            piece = part
        elif len(piece) + len(joiner) + len(part) <= max_chars:
            piece += joiner + part
        else:
            pieces.append(piece)
            piece = part
    return [*pieces, piece] if piece else pieces


# What renders a record chunk, as a chunker's identity names what cut a body
# chunk (R18.9): moved whenever the rendering of `field: value` lines changes.
RECORD_CHUNKER = "record@1"


def record_chunk_id(*, document_id: str, embedded: Sequence[str], index: int, text: str) -> str:
    """A record chunk's id: what rendered it, and the fields it renders (R18.2, R18.9).

    Carrying another field re-files it, as another chunker re-cuts a body.
    """
    return chunk_id(
        document_id=document_id,
        chunker=RECORD_CHUNKER,
        settings={"embed": list(embedded)},
        index=index,
        text=text,
    )


class HeadingsChunker:
    """The `headings` chunker, as the `Chunker` port asks for one (R18.1, R18.2).

    Its identity and settings travel into every chunk id it cuts, so an index
    cut under other settings is cut again rather than mixed.
    """

    def __init__(self, *, max_chars: int) -> None:
        self.identity = HEADINGS_CHUNKER
        self.settings = {"max_chars": max_chars}
        self._max_chars = max_chars

    def chunk(self, text: str) -> list[Chunk]:
        return heading_chunks(text, max_chars=self._max_chars)


def chunk_id(
    *,
    document_id: str,
    chunker: str,
    settings: Mapping[str, object],
    index: int,
    text: str,
) -> str:
    """The hash of a chunk's document, chunker, settings, position and text (R18.2).

    The document is in it, so one sentence in two documents is two chunks.
    The chunker and its settings are in it, because a chunk cut under others
    is another chunk, even when its text comes out the same (R0.5). Taken over
    canonical JSON, keys sorted and text as UTF-8, so the id is the same bytes
    on every machine whatever order the settings were declared in (R0.4).
    """
    keyed = {
        "chunker": chunker,
        "document": document_id,
        "index": index,
        "settings": dict(settings),
        "text": text,
    }
    canonical = json.dumps(keyed, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return content_hash(canonical.encode("utf-8"))
