"""R18.1 — a document is cut into chunks at its headings, and each chunk carries
the headings above it.

A section longer than the chunker's `max_chars` is cut at paragraph breaks, and
a paragraph longer than it at a sentence's end, then at a space. Every piece
keeps its section's heading path.

The decision is `heading_chunks`: a document's converted text and `max_chars`
in, its chunks out. The values are `_fixtures.md`'s: `INC-4821`'s note states
its loss, `CHF 48'200`, under `Impact`, and `m.keller` comments first.
"""

from __future__ import annotations

import pytest

from dossier.domain.chunks import Chunk, heading_chunks

TITLE = "INC-4821 — Card payments declined at checkout"

# `INC-4821` as dossier's Jira note renders it: the summary as the one `#`
# heading, the fields beneath it, then a `##` section per part of the issue.
# `Description` is empty, as the issue's own description field leaves it here.
NOTE = """\
# INC-4821 — Card payments declined at checkout

**Status:** Done
**Type:** Incident
**Priority:** High

## Description

## Impact

Finance confirmed a total exposure of CHF 48'200 in late-settlement interest.

## Comments

**m.keller** wrote: Declines started at 09:12.
"""


def paragraph(length: int) -> str:
    """Prose of exactly `length` characters, ending in a full stop, with no break in it."""
    return ("Declines rose at the gateway. " * length)[: length - 1] + "."


def sentence(number: int, length: int) -> str:
    """One sentence of exactly `length` characters, with no sentence end before its last."""
    return (f"Decline {number:02d} was confirmed by finance " * length)[: length - 1] + "."


class TestADocumentIsCutAtItsHeadings:
    """R18.1 — one chunk per section, each carrying the headings above it."""

    def test_the_impact_is_a_chunk_beneath_the_issue_and_its_section(self):
        """Row 1 — the one where `INC-4821`'s note states `CHF 48'200` under `## Impact`.

        `Description` has no text, so it is no chunk: an empty section would
        be a vector of nothing but its headings.
        """
        chunks = heading_chunks(NOTE, max_chars=2000)

        [holding] = [chunk for chunk in chunks if "CHF 48'200" in chunk.text]
        assert holding.heading_path == (TITLE, "Impact")
        assert chunks == [
            Chunk(
                index=0,
                heading_path=(TITLE,),
                text="**Status:** Done\n**Type:** Incident\n**Priority:** High",
            ),
            Chunk(
                index=1,
                heading_path=(TITLE, "Impact"),
                text=(
                    "Finance confirmed a total exposure of CHF 48'200"
                    " in late-settlement interest."
                ),
            ),
            Chunk(
                index=2,
                heading_path=(TITLE, "Comments"),
                text="**m.keller** wrote: Declines started at 09:12.",
            ),
        ]

    def test_a_shallower_heading_closes_every_deeper_one(self):
        """Row 1, continued — the one where a `###` under `Impact` is followed by `## Comments`.

        A heading of one level replaces every heading at that level or deeper,
        so `Comments` is not filed under `Impact` or its subsection.
        """
        text = (
            f"# {TITLE}\n\n## Impact\n\n### Settlement\n\n"
            "Interest accrued on late settlement.\n\n## Comments\n\nDeclines started at 09:12."
        )

        assert [chunk.heading_path for chunk in heading_chunks(text, max_chars=2000)] == [
            (TITLE, "Impact", "Settlement"),
            (TITLE, "Comments"),
        ]

    def test_a_hash_inside_a_code_block_is_not_a_heading(self):
        """Row 1, continued — the one where a comment quotes a shell session in a fence.

        `# restart` is a prompt the commander pasted, not a section of the
        issue: cutting there would file the rest of the comment under it.
        """
        text = (
            f"# {TITLE}\n\n## Comments\n\n**m.keller** wrote:\n\n"
            "```\n# restart payments-api\n```\n\nDeclines stopped at 09:40."
        )

        assert heading_chunks(text, max_chars=2000) == [
            Chunk(
                index=0,
                heading_path=(TITLE, "Comments"),
                text=(
                    "**m.keller** wrote:\n\n```\n# restart payments-api\n```\n\n"
                    "Declines stopped at 09:40."
                ),
            )
        ]

    def test_a_note_with_windows_line_endings_is_cut_the_same(self):
        """Row 1, continued — the one checked out with CRLF line endings.

        The same note is the same chunks on every machine (R0.4), and a
        heading line ending in a carriage return is still a heading.
        """
        assert heading_chunks(NOTE.replace("\n", "\r\n"), max_chars=2000) == heading_chunks(
            NOTE, max_chars=2000
        )

    def test_a_long_section_is_cut_at_its_paragraph_breaks(self):
        """Row 2 — the one where a section of 5,200 characters holds four paragraphs.

        The first two fit in one piece together; the last two each fill most
        of one. Every piece keeps the section's heading path.
        """
        first, second, third, fourth = (paragraph(n) for n in (1500, 400, 1800, 1494))
        section = "\n\n".join([first, second, third, fourth])
        assert len(section) == 5200

        chunks = heading_chunks(f"# {TITLE}\n\n## Impact\n\n{section}\n", max_chars=2000)

        assert chunks == [
            Chunk(index=0, heading_path=(TITLE, "Impact"), text=f"{first}\n\n{second}"),
            Chunk(index=1, heading_path=(TITLE, "Impact"), text=third),
            Chunk(index=2, heading_path=(TITLE, "Impact"), text=fourth),
        ]
        assert max(len(chunk.text) for chunk in chunks) <= 2000
        assert "\n\n".join(chunk.text for chunk in chunks) == section

    def test_a_paragraph_too_long_for_one_piece_is_cut_at_a_sentence_end(self):
        """Row 3, counter-example — the one where one paragraph runs 2,600 characters.

        Nineteen sentences of 100 characters fill 1,918 of the 2,000; the
        twentieth would not fit, so the cut falls after the nineteenth's full
        stop, not inside the twentieth.
        """
        sentences = [sentence(number, 100) for number in range(1, 26)] + [sentence(26, 75)]
        text = " ".join(sentences)
        assert len(text) == 2600

        chunks = heading_chunks(f"## Impact\n\n{text}", max_chars=2000)

        assert chunks == [
            Chunk(index=0, heading_path=("Impact",), text=" ".join(sentences[:19])),
            Chunk(index=1, heading_path=("Impact",), text=" ".join(sentences[19:])),
        ]
        assert [len(chunk.text) for chunk in chunks] == [1918, 681]
        assert chunks[0].text.endswith(sentences[18])

    def test_a_sentence_too_long_for_one_piece_is_cut_at_a_space(self):
        """Row 3, counter-example — the one where the 2,600 characters hold no sentence end.

        222 words of eight letters fill 1,997 characters; the cut falls at the
        space after the 222nd, and no word is split.
        """
        words = ["declined"] * 289
        text = " ".join(words)
        assert len(text) == 2600

        chunks = heading_chunks(text, max_chars=2000)

        assert chunks == [
            Chunk(index=0, heading_path=(), text=" ".join(words[:222])),
            Chunk(index=1, heading_path=(), text=" ".join(words[222:])),
        ]

    def test_a_word_too_long_for_one_piece_is_cut_every_max_chars(self):
        """Row 3, counter-example — the one where a pasted trace id has no space at all.

        There is nowhere better to cut, and no piece is ever longer than
        `max_chars`, so it is cut every 2,000 characters.
        """
        trace = "0123456789abcdef" * 300

        chunks = heading_chunks(trace, max_chars=2000)

        assert [chunk.text for chunk in chunks] == [
            trace[:2000],
            trace[2000:4000],
            trace[4000:],
        ]

    def test_a_document_with_no_heading_is_one_path_of_none(self):
        """Row 4, counter-example — the one where `audit-note.pdf`'s text has no heading at all.

        Its path is empty, not invented: the document's title is its key, and
        the index carries that apart from the chunk.
        """
        text = "Audit note\n\nThe checkout path was reviewed after the declines of 28 July."

        assert heading_chunks(text, max_chars=2000) == [
            Chunk(index=0, heading_path=(), text=text),
        ]

    def test_an_empty_document_is_no_chunk(self):
        """Row 5, counter-example — the one where `handover-note.md` is zero bytes."""
        assert heading_chunks("", max_chars=2000) == []

    def test_a_hash_in_a_heading_is_its_text_and_a_closing_run_is_not(self):
        """No row — the one about C#, and the one closed by its own hashes.

        A heading's text is what the heading path carries into every chunk
        beneath it and into the text embedded (R18.3), so it is read as
        written: only a run of `#` after a space closes it.
        """
        text = "## Why C#\n\nThe batch was ported.\n\n## Impact ##\n\nCHF 48'200.\n"

        assert [chunk.heading_path for chunk in heading_chunks(text, max_chars=2000)] == [
            ("Why C#",),
            ("Impact",),
        ]

    def test_max_chars_below_one_is_refused(self):
        """No row — the guard that keeps "no piece longer than `max_chars`" satisfiable.

        A piece of at most zero characters holds nothing, so cutting under it
        could never end.
        """
        with pytest.raises(ValueError, match="max_chars"):
            heading_chunks(NOTE, max_chars=0)
