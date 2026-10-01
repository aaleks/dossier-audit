"""The embedding index in PostgreSQL with pgvector (spec 018, R18.4, R18.5).

Two tables in the schema `dossier_index`, as spec 018's "What it writes" names
them: `documents`, one row per document of every index, and `chunks`, one row
per chunk with its vector and its words.

One `chunks` table for every index, not one per index. Its `embedding` column
has one type, fixed by the first `prepare`: an HNSW index is built over a column
of fixed dimensions, and vectors of two models are not comparable anyway. An
index whose model answers in another type or length is refused, naming both,
and is built in another database, which its own `target.dsn_env` names. A table
per index would let any mix of models share one database, at the price of a
table the spec does not name, an SQL identifier built from a declaration's name,
and one view per index for the system that reads them. Each index's rows carry
its name, so one view serves every index, and the name is only ever a value
bound to a query.

The index is derived data, rebuilt from the workspace (R18.4). What `held`
reads back is the ids and content hashes of an index's documents, and nothing
else (R0.16 row 7).
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager

import psycopg
from pgvector import HalfVector, Vector
from pgvector.psycopg import register_vector
from psycopg import sql

from dossier.domain.index import IndexedChunk, IndexedDocument
from dossier.infrastructure.index import IndexSinkFailed

__all__ = ["SCHEMA", "IndexSinkFailed", "PostgresIndexSink"]

SCHEMA = "dossier_index"

# What R18.5 decides a column is: `halfvec(2560)`, `vector(1024)`. Checked
# before it is written into DDL, since a type cannot be a bound parameter.
_COLUMN = re.compile(r"^(halfvec|vector)\([1-9][0-9]{0,4}\)$")
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_COSINE = {"halfvec": "halfvec_cosine_ops", "vector": "vector_cosine_ops"}

_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS {schema}.documents (
    "index" text NOT NULL,
    document_id text NOT NULL,
    source_id text NOT NULL,
    key text NOT NULL,
    title text NOT NULL,
    snapshot text NOT NULL,
    acl text[] NOT NULL,
    embedding_model text NOT NULL,
    content_hash text NOT NULL,
    run_id text,
    filter_values jsonb NOT NULL DEFAULT '{{}}',
    PRIMARY KEY ("index", document_id)
)
"""

# `simple`: no stemming and no stop words, because incidents are written in
# more than one language, and a stemmer for the wrong one mangles words.
_CHUNKS = """
CREATE TABLE IF NOT EXISTS {schema}.chunks (
    "index" text NOT NULL,
    chunk_id text NOT NULL,
    document_id text NOT NULL,
    kind text NOT NULL,
    chunk_index integer NOT NULL,
    heading_path text[] NOT NULL,
    text text NOT NULL,
    acl text[] NOT NULL,
    embedding {column} NOT NULL,
    text_search tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    PRIMARY KEY ("index", chunk_id),
    FOREIGN KEY ("index", document_id)
        REFERENCES {schema}.documents ("index", document_id) ON DELETE CASCADE
)
"""

_CHUNK_INDEXES = (
    'CREATE INDEX IF NOT EXISTS chunks_document ON {schema}.chunks ("index", document_id)',
    "CREATE INDEX IF NOT EXISTS chunks_embedding ON {schema}.chunks "
    "USING hnsw (embedding {cosine})",
    "CREATE INDEX IF NOT EXISTS chunks_text_search ON {schema}.chunks USING gin (text_search)",
)


class PostgresIndexSink:
    """Writes an index's rows to Postgres, over one connection opened when first asked.

    `schema` is `dossier_index`; a test passes its own, so it never writes into
    an index someone is reading. One operation at a time: the connection is
    shared, and two transactions interleaved on it would be one.
    """

    def __init__(self, dsn: str, *, schema: str = SCHEMA) -> None:
        if not _SCHEMA_NAME.match(schema):
            raise IndexSinkFailed(f"{schema!r} is not a schema name dossier writes to")
        self._dsn = dsn
        self._name = schema
        self._schema = sql.Identifier(schema)
        self._connection: psycopg.Connection | None = None
        self._registered = False
        self._lock = threading.Lock()

    def prepare(self, index: str, column: str) -> None:
        """Create the schema, both tables and their indexes, where they are absent.

        Refuses, naming both, when `chunks` already holds vectors of another
        type or length than `column`: vectors from two models are not
        comparable, and would be ranked against each other as if they were.
        """
        if not _COLUMN.match(column):
            raise IndexSinkFailed(
                f"index {index!r} asks for a vector column {column!r}; expected "
                "halfvec(<dimensions>) or vector(<dimensions>)"
            )
        with self._session(f"preparing index {index!r}") as connection:
            with connection.transaction():
                connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
                connection.execute(self._sql("CREATE SCHEMA IF NOT EXISTS {schema}"))
                connection.execute(self._sql(_DOCUMENTS))
                connection.execute(self._sql(_CHUNKS, column=sql.SQL(column)))
                held = self._embedding_column(connection)
                if held != column:
                    raise IndexSinkFailed(
                        f"{self._name}.chunks holds embedding {held}, and index {index!r} "
                        f"asks for {column}. Vectors of two models are not mixed in one "
                        "table: point the index at another database, or drop the schema "
                        "and embed every index again (the index is derived data, R18.4)."
                    )
                cosine = sql.SQL(_COSINE[column.partition("(")[0]])
                for statement in _CHUNK_INDEXES:
                    connection.execute(self._sql(statement, cosine=cosine))
            self._register(connection)

    def held(self, index: str) -> Mapping[str, str]:
        """`document_id -> content_hash` for every document `index` holds.

        Empty when nothing has been prepared yet: the first `dossier embed` asks
        what is held before anything has created the tables.
        """
        with self._session(f"reading what index {index!r} holds") as connection:
            if not self._exists(connection, "documents"):
                return {}
            rows = connection.execute(
                self._sql(
                    "SELECT document_id, content_hash FROM {schema}.documents "
                    'WHERE "index" = %s ORDER BY document_id'
                ),
                (index,),
            ).fetchall()
        return dict(rows)

    def write(
        self, index: str, document: IndexedDocument, chunks: Sequence[IndexedChunk]
    ) -> None:
        """Replace `document`'s rows in `index` with these, in one transaction.

        A reader sees the old rows or the new ones, never a document with half
        its chunks: a failure part way rolls the whole document back.
        """
        if document.index != index:
            raise IndexSinkFailed(
                f"{document.document_id} belongs to index {document.index!r}, not {index!r}"
            )
        doing = f"writing {document.document_id} to index {index!r}"
        with self._session(doing) as connection:
            held = self._embedding_column(connection)
            if held is None:
                raise IndexSinkFailed(f"{doing}: {self._name}.chunks does not exist yet")
            self._register(connection)
            as_vector = HalfVector if held.startswith("halfvec") else Vector
            with connection.transaction():
                for table in ("chunks", "documents"):
                    connection.execute(
                        self._sql(
                            f'DELETE FROM {{schema}}.{table} WHERE "index" = %s '
                            "AND document_id = %s"
                        ),
                        (index, document.document_id),
                    )
                connection.execute(
                    self._sql(
                        'INSERT INTO {schema}.documents ("index", document_id, source_id, '
                        "key, title, snapshot, acl, embedding_model, content_hash) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    ),
                    (
                        index,
                        document.document_id,
                        document.source_id,
                        document.key,
                        document.title,
                        document.snapshot,
                        list(document.acl),
                        document.embedding_model,
                        document.content_hash,
                    ),
                )
                with connection.cursor() as cursor:
                    cursor.executemany(
                        self._sql(
                            'INSERT INTO {schema}.chunks ("index", chunk_id, document_id, '
                            "kind, chunk_index, heading_path, text, acl, embedding) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                        ),
                        [
                            (
                                index,
                                chunk.chunk_id,
                                chunk.document_id,
                                chunk.kind,
                                chunk.chunk_index,
                                list(chunk.heading_path),
                                chunk.text,
                                list(chunk.acl),
                                as_vector(list(chunk.embedding)),
                            )
                            for chunk in chunks
                        ],
                    )

    def remove(self, index: str, document_ids: Sequence[str]) -> None:
        """Delete these documents' rows and chunks from `index`, in one transaction.

        Nothing to delete where nothing was prepared: an index never written
        holds no document to remove.
        """
        if not document_ids:
            return
        with self._session(f"removing documents from index {index!r}") as connection:
            if not self._exists(connection, "documents"):
                return
            tables = [
                table for table in ("chunks", "documents") if self._exists(connection, table)
            ]
            with connection.transaction():
                for table in tables:
                    connection.execute(
                        self._sql(
                            f'DELETE FROM {{schema}}.{table} WHERE "index" = %s '
                            "AND document_id = ANY(%s)"
                        ),
                        (index, list(document_ids)),
                    )

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> PostgresIndexSink:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @contextmanager
    def _session(self, doing: str) -> Iterator[psycopg.Connection]:
        """The connection, opened on first use and again after it broke.

        Autocommit, so a read leaves no transaction open; each write opens its
        own. A driver's error is reported as what was being done when it came.
        """
        with self._lock:
            try:
                if self._connection is None or self._connection.closed:
                    self._connection = psycopg.connect(self._dsn, autocommit=True)
                    self._registered = False
                yield self._connection
            except psycopg.Error as error:
                if self._connection is not None and self._connection.broken:
                    self._connection = None
                said = " ".join(str(error).split())
                raise IndexSinkFailed(f"{doing} failed: {said}") from error

    def _register(self, connection: psycopg.Connection) -> None:
        # Only once the extension exists: the types are looked up in the database.
        if not self._registered:
            register_vector(connection)
            self._registered = True

    def _exists(self, connection: psycopg.Connection, table: str) -> bool:
        found = connection.execute(
            "SELECT to_regclass(%s)", (f"{self._name}.{table}",)
        ).fetchone()
        return found is not None and found[0] is not None

    def _embedding_column(self, connection: psycopg.Connection) -> str | None:
        """`halfvec(2560)`, as Postgres writes the type `chunks.embedding` holds, or `None`."""
        found = connection.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = to_regclass(%s) AND attname = 'embedding' "
            "AND NOT attisdropped",
            (f"{self._name}.chunks",),
        ).fetchone()
        return None if found is None else found[0]

    def _sql(self, template: str, **parts: sql.Composable) -> sql.Composed:
        return sql.SQL(template).format(schema=self._schema, **parts)
