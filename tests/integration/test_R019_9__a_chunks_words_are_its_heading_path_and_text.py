"""R19.9 -- a chunk's words are its heading path and its text, the text its
vector was made from.

A note's key and title are in its first heading, which every chunk beneath it
carries in its heading path and none holds in its text. Words generated from
the text alone missed what the vector read: the live check of R19.8 listed
`PLAY-1004` third for the query `PLAY-1004`. Here, against a real PostgreSQL
with pgvector, through `PostgresIndexSearch`'s list by words, and the column
compared with `embedding_text`, which composes what R18.3 embeds.

`live`: it needs a server, so it is out of the default suite and runs only when
`DOSSIER_INDEX_DSN` names one (`dev/index/docker-compose.yml`). Every test
writes into a schema of its own, dropped afterwards.
"""

from __future__ import annotations

import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("pgvector")

from tests.fakes import FakeEmbeddingProvider  # noqa: E402

from dossier.domain.index import Embedded, embedding_text, indexed  # noqa: E402
from dossier.infrastructure.index.postgres import (  # noqa: E402
    PostgresIndexSearch,
    PostgresIndexSink,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("DOSSIER_INDEX_DSN"),
        reason="DOSSIER_INDEX_DSN names no index server (dev/index/docker-compose.yml)",
    ),
]

MODEL = (
    "ollama:qwen3-embedding:4b-fp16"
    "@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
)
COLUMN = "halfvec(2560)"
INDEX = "incidents"
TITLE = "INC-4821 — Card payments declined at checkout"


def meaning(text: str) -> tuple[float, ...]:
    """The 2,560 values `FakeEmbeddingProvider` gives `text`."""
    return tuple(FakeEmbeddingProvider().embed([text])[0])


def chunk(chunk_id: str, index: int, heading_path: tuple[str, ...], text: str) -> Embedded:
    return Embedded(
        chunk_id=chunk_id,
        kind="body",
        chunk_index=index,
        heading_path=heading_path,
        text=text,
        embedding=meaning(embedding_text(heading_path, text)),
    )


# `INC-4821` is in neither text, and neither holds `declined` or `checkout`.
IMPACT = chunk("c-impact", 0, (TITLE, "Impact"), "A recorded loss of CHF 48'200.")
COMMENTS = chunk("c-comments", 1, (TITLE, "Comments"), "Rolled back the gateway at 14:40.")
# A PDF with no heading at all: its title is its key (R18.2 row 4).
AUDIT_NOTE = chunk("c-audit-note", 0, (), "Quarterly audit of card payment incidents.")


def write(sink: PostgresIndexSink, key: str, *chunks: Embedded, source: str) -> None:
    row, written = indexed(
        index=INDEX,
        source_id=source,
        key=key,
        title=key,
        snapshot="a3f9c1e2",
        acl=("incident-response",),
        embedding_model=MODEL,
        chunks=list(chunks),
        values=None,
    )
    sink.write(INDEX, row, written)


def by_words(search: PostgresIndexSearch, query: str) -> list[str]:
    found = search.search(
        INDEX, vector=meaning(query), words=query, where={}, readers=None, candidates=100
    )
    return [candidate.chunk_id for candidate in found.words]


@pytest.fixture(scope="module")
def dsn() -> str:
    return os.environ["DOSSIER_INDEX_DSN"]


@pytest.fixture
def schema(dsn: str):
    name = f"dossier_index_test_{uuid.uuid4().hex[:12]}"
    yield name
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")


@pytest.fixture
def query(dsn: str):
    def run(statement: str, *params: object) -> list[tuple]:
        with psycopg.connect(dsn, autocommit=True) as connection:
            cursor = connection.execute(statement, params or None)
            return cursor.fetchall() if cursor.description is not None else []

    return run


@pytest.fixture
def sink(dsn: str, schema: str):
    with PostgresIndexSink(dsn, schema=schema) as opened:
        opened.prepare(INDEX, COLUMN)
        yield opened


@pytest.fixture
def search(dsn: str, schema: str):
    with PostgresIndexSearch(dsn, schema=schema) as opened:
        yield opened


@pytest.fixture
def inc_4821(sink: PostgresIndexSink) -> None:
    write(sink, "INC-4821", IMPACT, COMMENTS, source="incidents-jira")


class TestAChunksWordsAreItsHeadingPathAndText:
    """R19.9 -- `text_search` is the `tsvector` of what R18.3 embeds."""

    def test_a_key_held_only_in_the_heading_is_found_by_words(self, inc_4821, search):
        """The one where `INC-4821` is in the title, and in no chunk's text (row 1)."""
        assert "c-impact" in by_words(search, "INC-4821")

    def test_words_of_the_title_find_every_chunk_beneath_it(self, inc_4821, search):
        """The one where `declined at checkout` is in the title both chunks carry (row 2)."""
        assert sorted(by_words(search, "declined at checkout")) == ["c-comments", "c-impact"]

    def test_a_chunks_words_are_those_of_the_text_it_was_embedded_as(
        self, inc_4821, schema, query
    ):
        """The one where the words and the vector read one text, composed once (rows 1, 2)."""
        for embedded in (IMPACT, COMMENTS):
            [(same,)] = query(
                f"SELECT text_search = to_tsvector('simple', %s) FROM {schema}.chunks "
                "WHERE chunk_id = %s",
                embedding_text(embedded.heading_path, embedded.text),
                embedded.chunk_id,
            )
            assert same, embedded.chunk_id

    def test_an_index_written_before_has_its_words_rebuilt_when_prepared(
        self, inc_4821, sink, search, schema, query
    ):
        """The one where an old index's words were its texts alone, and are rebuilt (row 3).

        The column is put back as it was before R19.9, generated from `text`,
        and the key is found by no word. Prepared again, as each `dossier
        embed` prepares it, the words are rebuilt from the heading paths and
        texts held, and each chunk keeps its id and its vector.
        """
        query(f"ALTER TABLE {schema}.chunks DROP COLUMN text_search")
        query(
            f"ALTER TABLE {schema}.chunks ADD COLUMN text_search tsvector "
            "GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED"
        )
        vectors = f"SELECT chunk_id, embedding::text FROM {schema}.chunks ORDER BY 1"
        held = query(vectors)
        assert by_words(search, "INC-4821") == []

        sink.prepare(INDEX, COLUMN)

        assert "c-impact" in by_words(search, "INC-4821")
        assert query(vectors) == held
        [(generated, not_null)] = query(
            "SELECT attgenerated::text, attnotnull FROM pg_attribute "
            "WHERE attrelid = to_regclass(%s) AND attname = 'text_search'",
            f"{schema}.chunks",
        )
        assert (generated, not_null) == ("", True)

    def test_a_chunk_with_no_heading_has_the_words_of_its_text_alone(self, sink, schema, query):
        """The one where `audit-note.pdf` has no heading, and nothing is added (row 4)."""
        write(sink, "audit-note.pdf", AUDIT_NOTE, source="incidents-manual")

        [(words, of_text)] = query(
            f"SELECT text_search::text, to_tsvector('simple', text)::text FROM {schema}.chunks "
            "WHERE chunk_id = 'c-audit-note'"
        )
        assert words == of_text
