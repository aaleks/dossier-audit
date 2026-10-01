"""R18.4 -- the Postgres index sink, against a real PostgreSQL with pgvector.

R18.4's rows are proved by `test_R018_4__the_index_holds_the_active_documents.py`
against a fake sink. This file proves the fake is a claim about a real one:
that `prepare`, `held`, `write` and `remove` do to Postgres what the fake says
they do, and that the rows they write are searched by words and by meaning.

`live`: it needs a server, so it is out of the default suite and runs only when
`DOSSIER_INDEX_DSN` names one (`dev/index/docker-compose.yml`). Every test
writes into a schema of its own, dropped afterwards, so it never touches an
index anyone reads.
"""

from __future__ import annotations

import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")
pgvector = pytest.importorskip("pgvector")

from pgvector import HalfVector  # noqa: E402 -- after the extra is found
from pgvector.psycopg import register_vector  # noqa: E402

from dossier.domain.index import Embedded, indexed  # noqa: E402
from dossier.infrastructure.index import IndexSinkFailed  # noqa: E402
from dossier.infrastructure.index.postgres import PostgresIndexSink  # noqa: E402

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
DIMENSIONS = 2560
INDEX = "incidents"
TITLE = "INC-4821 — Card payments declined at checkout"


def along(*weights: float) -> tuple[float, ...]:
    """A 2,560-value vector: these weights first, zeros after."""
    return tuple(weights) + (0.0,) * (DIMENSIONS - len(weights))


IMPACT = Embedded(
    chunk_id="c-impact",
    kind="body",
    chunk_index=0,
    heading_path=(TITLE, "Impact"),
    text="CHF 48'200 in card payments declined at checkout.",
    embedding=along(1.0, 0.0),
)
COMMENTS = Embedded(
    chunk_id="c-comments",
    kind="body",
    chunk_index=1,
    heading_path=(TITLE, "Comments"),
    text="Rolled back the gateway release at 14:40.",
    embedding=along(0.0, 1.0),
)


def document(*chunks: Embedded, key: str = "INC-4821", snapshot: str = "a3f9c1e2"):
    return indexed(
        index=INDEX,
        source_id="incidents-jira",
        key=key,
        title=TITLE,
        snapshot=snapshot,
        acl=("incident-response",),
        embedding_model=MODEL,
        chunks=list(chunks),
    )


@pytest.fixture
def dsn() -> str:
    return os.environ["DOSSIER_INDEX_DSN"]


@pytest.fixture
def schema(dsn: str):
    name = f"dossier_index_test_{uuid.uuid4().hex[:12]}"
    yield name
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")


@pytest.fixture
def sink(dsn: str, schema: str):
    with PostgresIndexSink(dsn, schema=schema) as opened:
        yield opened


@pytest.fixture
def query(dsn: str):
    """Rows as a reader of the index sees them, over a connection of its own.

    The vector types are registered at the first question, not before: on a
    fresh database the extension exists only once `prepare` has created it.
    """
    with psycopg.connect(dsn, autocommit=True) as connection:
        registered = []

        def ask(statement: str, *params):
            if not registered:
                register_vector(connection)
                registered.append(True)
            return connection.execute(statement, params).fetchall()

        yield ask


class TestPostgresIndexSink:
    """R18.4 -- what the index holds is what was last written, and nothing of before."""

    def test_nothing_is_held_and_nothing_removed_before_anything_is_prepared(self, sink):
        """No row — the first `dossier embed` asks what is held before any table exists."""
        assert sink.held(INDEX) == {}
        sink.remove(INDEX, ["incidents-jira:INC-4821"])

    def test_prepare_creates_a_halfvec_column_under_hnsw_and_gin_indexes(
        self, sink, schema, query
    ):
        """No row — `halfvec(2560)` for Qwen3-Embedding-4B, as spec 018 writes it (R18.5 row 1).

        A second `prepare` changes nothing: it runs before every embed.
        """
        sink.prepare(INDEX, COLUMN)
        sink.prepare(INDEX, COLUMN)

        [(column,)] = query(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = to_regclass(%s) AND attname = 'embedding'",
            f"{schema}.chunks",
        )
        assert column == COLUMN
        indexes = dict(
            query("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %s", schema)
        )
        assert "USING hnsw (embedding halfvec_cosine_ops)" in indexes["chunks_embedding"]
        assert "USING gin (text_search)" in indexes["chunks_text_search"]
        assert sink.held(INDEX) == {}

    def test_a_written_document_is_held_with_its_content_hash_and_its_chunks(
        self, sink, schema, query
    ):
        """No row — a document of two chunks: one document row, two chunk rows, one hash."""
        sink.prepare(INDEX, COLUMN)
        row, chunks = document(IMPACT, COMMENTS)

        sink.write(INDEX, row, chunks)

        assert sink.held(INDEX) == {"incidents-jira:INC-4821": row.content_hash}
        # Another index's name holds none of it.
        assert sink.held("procedures") == {}
        assert query(
            f"SELECT chunk_id, chunk_index, heading_path, acl FROM {schema}.chunks "
            "ORDER BY chunk_index"
        ) == [
            ("c-impact", 0, [TITLE, "Impact"], ["incident-response"]),
            ("c-comments", 1, [TITLE, "Comments"], ["incident-response"]),
        ]
        assert query(f"SELECT acl, run_id, filter_values FROM {schema}.documents") == [
            (["incident-response"], None, {})
        ]

    def test_a_documents_run_and_its_grounded_values_are_written(self, sink, schema, query):
        """No row — R18.11's record, as the database holds it.

        Found by the live check that closed slice 2: the document row's run and
        values reached the fake index and not the real one.
        """
        sink.prepare(INDEX, COLUMN)
        row, chunks = indexed(
            index=INDEX,
            source_id="incidents-jira",
            key="INC-4830",
            title="INC-4830",
            snapshot="a3f9c1e2",
            acl=("incident-response",),
            embedding_model=MODEL,
            chunks=[IMPACT],
            run_id="20260925T091500Z-5e6f",
            values={"failure_category": "certificate-expiry", "component": "checkout"},
        )

        sink.write(INDEX, row, chunks)

        assert query(f"SELECT run_id, filter_values FROM {schema}.documents") == [
            (
                "20260925T091500Z-5e6f",
                {"component": "checkout", "failure_category": "certificate-expiry"},
            )
        ]

    def test_a_second_write_replaces_the_document_and_every_chunk_of_it(
        self, sink, schema, query
    ):
        """No row — `INC-4821` re-synced to one chunk: the old two go, the new hash is held."""
        sink.prepare(INDEX, COLUMN)
        sink.write(INDEX, *document(IMPACT, COMMENTS))
        row, chunks = document(IMPACT, snapshot="b7e2d4f0")

        sink.write(INDEX, row, chunks)

        assert sink.held(INDEX) == {"incidents-jira:INC-4821": row.content_hash}
        assert query(f"SELECT chunk_id FROM {schema}.chunks") == [("c-impact",)]

    def test_a_write_the_database_refuses_leaves_the_last_one_whole(self, sink, schema, query):
        """No row — a vector of 1,024 values in a 2,560 index rolls the whole document back.

        The delete of the old rows was in the same transaction, so the old rows
        are still there, whole: a reader never sees a document half replaced.
        """
        sink.prepare(INDEX, COLUMN)
        first, chunks = document(IMPACT, COMMENTS)
        sink.write(INDEX, first, chunks)
        short = Embedded(
            chunk_id="c-short",
            kind="body",
            chunk_index=0,
            heading_path=(TITLE,),
            text="Short.",
            embedding=(1.0,) * 1024,
        )

        with pytest.raises(IndexSinkFailed, match="incidents-jira:INC-4821"):
            sink.write(INDEX, *document(short, snapshot="b7e2d4f0"))

        assert sink.held(INDEX) == {"incidents-jira:INC-4821": first.content_hash}
        assert len(query(f"SELECT chunk_id FROM {schema}.chunks")) == 2

    def test_remove_deletes_the_document_and_its_chunks_and_nothing_else(
        self, sink, schema, query
    ):
        """No row — `INC-4821` removed: its document row and chunks go, `INC-4822`'s stay."""
        sink.prepare(INDEX, COLUMN)
        sink.write(INDEX, *document(IMPACT, COMMENTS))
        kept, kept_chunks = document(
            Embedded("c-4822", "body", 0, ("INC-4822",), "Timeouts.", along(0.5, 0.5)),
            key="INC-4822",
        )
        sink.write(INDEX, kept, kept_chunks)

        sink.remove(INDEX, ["incidents-jira:INC-4821"])

        assert sink.held(INDEX) == {"incidents-jira:INC-4822": kept.content_hash}
        assert query(f"SELECT chunk_id FROM {schema}.chunks") == [("c-4822",)]

    def test_a_column_of_another_type_is_refused_naming_both(self, sink):
        """No row — vectors of two models are not mixed in one table (R18.5)."""
        sink.prepare(INDEX, COLUMN)

        with pytest.raises(IndexSinkFailed) as refused:
            sink.prepare("procedures", "vector(1024)")

        assert "halfvec(2560)" in str(refused.value)
        assert "vector(1024)" in str(refused.value)

    def test_a_chunk_is_found_by_its_words_with_no_stemming(self, sink, schema, query):
        """No row — `text_search` is `simple`: `payments` is found, and `payment` is not.

        No stemming: incidents are written in more than one language (spec 018).
        """
        sink.prepare(INDEX, COLUMN)
        sink.write(INDEX, *document(IMPACT, COMMENTS))
        words = (
            f"SELECT chunk_id FROM {schema}.chunks "
            "WHERE text_search @@ plainto_tsquery('simple', %s)"
        )

        assert query(words, "gateway") == [("c-comments",)]
        assert query(words, "payments") == [("c-impact",)]
        assert query(words, "payment") == []

    def test_the_nearest_chunk_by_cosine_comes_first(self, sink, schema, query):
        """No row — by cosine distance, the chunk nearer the question comes first."""
        sink.prepare(INDEX, COLUMN)
        sink.write(INDEX, *document(IMPACT, COMMENTS))
        nearest = (
            f'SELECT chunk_id FROM {schema}.chunks WHERE "index" = %s '
            "ORDER BY embedding <=> %s LIMIT 2"
        )

        assert query(nearest, INDEX, HalfVector(list(along(0.9, 0.1)))) == [
            ("c-impact",),
            ("c-comments",),
        ]
        assert query(nearest, INDEX, HalfVector(list(along(0.2, 0.8)))) == [
            ("c-comments",),
            ("c-impact",),
        ]
