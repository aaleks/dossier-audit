"""R18.2 — a chunk's id is the hash of its document, its chunker and settings,
its position and its text.

The decision is `chunk_id`. Its id is what makes a second `dossier embed` with
nothing changed write nothing: a chunk whose id the index already holds is the
same chunk. The note is `INC-4821`'s, as R18.1's tests cut it.
"""

from __future__ import annotations

from tests.unit.test_R018_1__a_document_is_cut_at_its_headings import NOTE

from dossier.domain.chunks import HEADINGS_CHUNKER, chunk_id, heading_chunks

SETTINGS = {"max_chars": 2000}


def ids(text: str, *, document_id: str = "INC-4821", max_chars: int = 2000) -> list[str]:
    """The ids of `text`'s chunks, cut and named under `max_chars`, as `dossier embed` would."""
    return [
        chunk_id(
            document_id=document_id,
            chunker=HEADINGS_CHUNKER,
            settings={"max_chars": max_chars},
            index=chunk.index,
            text=chunk.text,
        )
        for chunk in heading_chunks(text, max_chars=max_chars)
    ]


class TestAChunkIdIsItsContent:
    """R18.2 — the same document, chunker, settings, position and text: the same id."""

    def test_the_impact_chunk_has_the_same_id_on_every_machine(self):
        """Row 1 — the one where `INC-4821` is cut on Windows and in `python:3.12-slim`.

        The id is pinned to its 64 characters, recomputed apart from `dossier`
        with `hashlib.sha256` over the canonical JSON. A test that only
        compared two ids taken on one machine would pass on a machine that
        hashed differently (R0.4).
        """
        [_, impact, _] = heading_chunks(NOTE, max_chars=2000)

        assert HEADINGS_CHUNKER == "headings@1"
        assert (
            chunk_id(
                document_id="INC-4821",
                chunker=HEADINGS_CHUNKER,
                settings=SETTINGS,
                index=impact.index,
                text=impact.text,
            )
            == "56c67341a1780f76122605f77a0e965917e4c7a703108be74d41f0a9aa2f32ae"
        )

    def test_a_chunk_beyond_ascii_has_the_same_id_on_every_machine(self):
        """Row 1, continued — the one where `m.keller`'s comment is written in German.

        Text is hashed as its UTF-8 bytes, so an umlaut or a dash is not
        rewritten as an escape on its way to the hash.
        """
        assert (
            chunk_id(
                document_id="INC-4821",
                chunker=HEADINGS_CHUNKER,
                settings=SETTINGS,
                index=2,
                text="**m.keller** schrieb: Zahlungen am Checkout abgelehnt — seit 09:12.",
            )
            == "2e61e21de7b6dab72307c9ab03ab72e3c61f6b32de5379942dd03b0141d89835"
        )

    def test_settings_declared_in_another_order_are_the_same_settings(self):
        """Row 1, continued — the one where an index declares its chunker's settings reordered.

        The order a YAML file lists them in is not a setting (R0.4).
        """
        named = {
            "document_id": "INC-4821",
            "chunker": HEADINGS_CHUNKER,
            "index": 0,
            "text": "**Status:** Done",
        }

        assert chunk_id(**named, settings={"max_chars": 2000, "name": "headings"}) == chunk_id(
            **named, settings={"name": "headings", "max_chars": 2000}
        )

    def test_a_changed_last_comment_leaves_every_chunk_before_it_alone(self):
        """Row 2 — the one where `INC-4821` is re-synced with only its last comment changed."""
        edited = NOTE.replace("Declines started at 09:12.", "Declines started at 09:10.")

        before, after = ids(NOTE), ids(edited)

        assert after[:-1] == before[:-1]
        assert after[-1] != before[-1]

    def test_a_chunk_cut_under_other_settings_is_another_chunk(self):
        """Row 3, counter-example — the one where `max_chars` drops from 2,000 to 1,000.

        Every section of the note is shorter than either, so the text of each
        chunk is the same and only the settings differ. Every id still changes:
        a chunk cut under other settings is another chunk (R0.5).
        """
        under_2000, under_1000 = ids(NOTE, max_chars=2000), ids(NOTE, max_chars=1000)

        assert len(under_2000) == len(under_1000) == 3
        assert set(under_2000).isdisjoint(under_1000)

    def test_a_chunk_cut_by_another_chunker_is_another_chunk(self):
        """Row 3, counter-example, continued — the one where the chunker's version moves.

        A chunker that cuts differently under the same name and settings
        re-chunks rather than mixing old and new pieces in one index (R0.5).
        """
        named = {
            "document_id": "INC-4821",
            "settings": SETTINGS,
            "index": 0,
            "text": "**Status:** Done",
        }

        assert chunk_id(**named, chunker="headings@1") != chunk_id(
            **named, chunker="headings@2"
        )

    def test_the_same_sentence_in_two_documents_is_two_chunks(self):
        """Row 4, counter-example — the one where `INC-4821` and `INC-4822` share a sentence.

        A chunk belongs to its document: one id for both would leave the
        second document's row pointing at the first's.
        """
        shared = {
            "chunker": HEADINGS_CHUNKER,
            "settings": SETTINGS,
            "index": 1,
            "text": "Declines started at 09:12.",
        }

        assert chunk_id(document_id="INC-4821", **shared) != chunk_id(
            document_id="INC-4822", **shared
        )

    def test_the_same_text_at_another_position_is_another_chunk(self):
        """No row — the one where one note repeats a sentence under two headings.

        Position is in the rule's own title: two identical paragraphs in one
        note are two rows, not one row written twice.
        """
        shared = {
            "document_id": "INC-4821",
            "chunker": HEADINGS_CHUNKER,
            "settings": SETTINGS,
            "text": "Declines started at 09:12.",
        }

        assert chunk_id(index=1, **shared) != chunk_id(index=2, **shared)
