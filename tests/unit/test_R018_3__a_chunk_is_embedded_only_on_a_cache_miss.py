"""R18.3 — a chunk is embedded only when the cache holds no vector for the pinned
model and the text it embeds.

The text embedded is the chunk's heading path, then its text. Its vector is
cached under the model and that text, as a stage's answer is cached under its
inputs (R5.5). The claims are about how many requests the model was sent, so
the fake counts them.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeEmbeddingProvider, FakeIndexSink

from dossier.application.embed import ToIndex, embed_index
from dossier.domain.chunks import HeadingsChunker
from dossier.domain.hashing import content_hash
from dossier.domain.index import IndexDeclaration
from dossier.infrastructure.cache import ArtifactCache

MODEL = (
    "ollama:qwen3-embedding:4b-fp16"
    "@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
)
OTHER = (
    "ollama:bge-m3:latest@sha256:"
    + "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
)
NOTE = (
    "# INC-4821 — Card payments declined at checkout\n\n"
    "**Status:** Done\n\n"
    "## Impact\n\n"
    "Finance confirmed a total exposure of CHF 48'200 in late-settlement interest.\n\n"
    "## Comments\n\n"
    "**m.keller** wrote: Declines started at 09:12.\n"
)


def declaration(*, name: str = "incidents", model: str = MODEL) -> IndexDeclaration:
    return IndexDeclaration(
        name=name,
        pipeline="incident-audit",
        embedding_model=model,
        chunker={"name": "headings", "max_chars": 2000},
        target={"dsn_env": "DOSSIER_INDEX_DSN"},
    )


def note(key: str, text: str) -> ToIndex:
    return ToIndex(
        source_id="incidents-jira",
        key=key,
        snapshot=content_hash(text.encode("utf-8")),
        text=text,
    )


def embed(workspace: Path, documents, embedder, *, index=None, sink=None):
    return embed_index(
        declaration=index or declaration(),
        documents=documents,
        readers={"incidents-jira": ("incident-response",)},
        chunker=HeadingsChunker(max_chars=2000),
        embedder=embedder,
        vectors=ArtifactCache(workspace, namespace="embed"),
        sink=sink if sink is not None else FakeIndexSink(),
    )


class TestAChunkIsEmbeddedOnlyOnACacheMiss:
    """R18.3 — the model is asked once for a text, whatever asks again."""

    def test_a_second_embed_with_nothing_synced_asks_nothing(self, tmp_path: Path):
        """Row 1 — the one embedded twice over the same note."""
        embedder = FakeEmbeddingProvider()
        embed(tmp_path, [note("INC-4821", NOTE)], embedder)
        asked = embedder.calls

        report = embed(tmp_path, [note("INC-4821", NOTE)], embedder)

        assert embedder.calls == asked
        assert (report.embedded, report.cached) == (0, 3)

    def test_an_edited_comment_asks_for_that_chunk_alone(self, tmp_path: Path):
        """Row 2 — the one whose last comment changed and was re-synced."""
        embedder = FakeEmbeddingProvider()
        embed(tmp_path, [note("INC-4821", NOTE)], embedder)
        asked = len(embedder.texts)
        edited = NOTE.replace("09:12", "09:14")

        embed(tmp_path, [note("INC-4821", edited)], embedder)

        assert embedder.texts[asked:] == [
            "INC-4821 — Card payments declined at checkout > Comments\n\n"
            "**m.keller** wrote: Declines started at 09:14."
        ]

    def test_another_model_embeds_every_chunk_again(self, tmp_path: Path):
        """Row 3, counter-example — the one whose embedding model was re-pinned.

        Vectors from two models are not comparable, so none is reused.
        """
        embedder = FakeEmbeddingProvider()
        embed(tmp_path, [note("INC-4821", NOTE)], embedder)
        asked = len(embedder.texts)

        embed(tmp_path, [note("INC-4821", NOTE)], embedder, index=declaration(model=OTHER))

        assert len(embedder.texts) - asked == 3

    def test_one_text_in_two_indexes_is_asked_once(self, tmp_path: Path):
        """Row 4, counter-example — the one filed in `incidents` and in `postmortems`.

        The vector is the model's answer to the text, whichever index files it.
        """
        embedder = FakeEmbeddingProvider()
        single = "# INC-4822\n\nFinance confirmed a total exposure CHF 12'500.\n"

        embed(tmp_path, [note("INC-4822", single)], embedder)
        embed(
            tmp_path,
            [note("INC-4822", single)],
            embedder,
            index=declaration(name="postmortems"),
        )

        assert embedder.calls == 1
        assert embedder.texts == ["INC-4822\n\nFinance confirmed a total exposure CHF 12'500."]
