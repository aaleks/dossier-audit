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

`PostgresIndexSearch` reads back what the index is for: chunks, their text, and
their documents' titles and values (spec 019, "Reading back from the index").
It is its own class, behind its own port, so the sink still reads back ids and
hashes alone, and what a search reads reaches the terminal and MLflow and
nothing else (R0.17).
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Self

import psycopg
from pgvector import HalfVector, Vector
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.types.json import Jsonb

from dossier.domain.index import IndexedChunk, IndexedDocument
from dossier.domain.search import Candidate, Described, Lists
from dossier.infrastructure.index import IndexSearchFailed, IndexSinkFailed

__all__ = [
    "SCHEMA",
    "IndexSearchFailed",
    "IndexSinkFailed",
    "PostgresIndexSearch",
    "PostgresIndexSink",
]

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


class _PostgresIndex:
    """One connection to the index's schema, opened when first asked, and its errors told.

    `schema` is `dossier_index`; a test passes its own, so it never touches an
    index someone is reading. One operation at a time: the connection is
    shared, and two transactions interleaved on it would be one.
    """

    # What a driver's error is raised as: what the caller was doing, in its terms.
    _failed: type[RuntimeError] = IndexSinkFailed

    def __init__(self, dsn: str, *, schema: str = SCHEMA) -> None:
        if not _SCHEMA_NAME.match(schema):
            raise self._failed(f"{schema!r} is not a schema name dossier writes to")
        self._dsn = dsn
        self._name = schema
        self._schema = sql.Identifier(schema)
        self._connection: psycopg.Connection | None = None
        self._registered = False
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> Self:
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
                raise self._failed(f"{doing} failed: {said}") from error

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


class PostgresIndexSink(_PostgresIndex):
    """Writes an index's rows to Postgres, over one connection opened when first asked."""

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
                        "key, title, snapshot, acl, embedding_model, content_hash, run_id, "
                        "filter_values) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
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
                        # The run whose grounded record the document carries,
                        # and the values to filter on that it gave (R18.8, R18.9).
                        document.run_id,
                        Jsonb(dict(document.values)),
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


# Both lists read a chunk with its document's title and carried values, so a
# search reads what it prints in the two queries that rank it.
_READ = "c.chunk_id, c.document_id, c.kind, c.heading_path, c.text, d.title, d.filter_values"
_FROM = (
    "FROM {schema}.chunks c JOIN {schema}.documents d "
    'ON d."index" = c."index" AND d.document_id = c.document_id '
    'WHERE c."index" = %(index)s{filters}'
)

# The chunk id breaks a tie, compared by its bytes as Python compares it: the
# database's collation would order `chunk-2` before `chunk1` on one server and
# after it on another, so a list would not be the same on every machine.
_TIE = 'chunk_id COLLATE "C"'

# Nearest first, by cosine distance: the operator class the HNSW index is built
# with (R18.5). `relaxed_order` lets the scan hand a chunk back slightly out of
# order, so the list is materialised and ordered again, as pgvector's README
# does. By `distance + 0`, as the README has it: Postgres 17 takes the order a
# materialised CTE was asked for as the order it holds, and would sort nothing.
_NEAREST = (
    "WITH nearest AS MATERIALIZED ("
    f"SELECT {_READ}, c.embedding <=> %(vector)s AS distance {_FROM} "
    f"ORDER BY distance, c.{_TIE} LIMIT %(candidates)s) "
    "SELECT chunk_id, document_id, kind, heading_path, text, title, filter_values "
    f"FROM nearest ORDER BY distance + 0, {_TIE}"
)

# Best first, by `ts_rank_cd`, over the chunks the query's words match, read in
# `simple` as the index was written (spec 018). A query of no words is an empty
# tsquery, which matches nothing: an empty list, not an error.
_MATCHING = (
    f"SELECT {_READ} {_FROM} "
    "AND c.text_search @@ websearch_to_tsquery('simple', %(words)s) "
    "ORDER BY ts_rank_cd(c.text_search, websearch_to_tsquery('simple', %(words)s)) DESC, "
    f"c.{_TIE} LIMIT %(candidates)s"
)


class PostgresIndexSearch(_PostgresIndex):
    """Searches an index in Postgres by meaning and by words (spec 019), as `IndexSearch`.

    It reads, and writes nothing: each search is one read-only transaction.
    """

    _failed = IndexSearchFailed

    def models(self, index: str) -> frozenset[str]:
        """The embedding models `index`'s documents were embedded with (R19.6).

        Empty when the index holds nothing, or nothing has been prepared yet.
        """
        with self._session(f"reading the models of index {index!r}") as connection:
            if not self._exists(connection, "documents"):
                return frozenset()
            rows = connection.execute(
                self._sql(
                    'SELECT DISTINCT embedding_model FROM {schema}.documents WHERE "index" = %s'
                ),
                (index,),
            ).fetchall()
        return frozenset(model for (model,) in rows)

    def snapshots(self, index: str) -> Mapping[str, str]:
        """`document_id -> snapshot` for every document `index` holds (R19.7).

        Empty when nothing has been prepared yet, as `held` is.
        """
        with self._session(f"reading the snapshots of index {index!r}") as connection:
            if not self._exists(connection, "documents"):
                return {}
            rows = connection.execute(
                self._sql(
                    "SELECT document_id, snapshot FROM {schema}.documents "
                    'WHERE "index" = %s ORDER BY document_id'
                ),
                (index,),
            ).fetchall()
        return dict(rows)

    def search(
        self,
        index: str,
        *,
        vector: Sequence[float],
        words: str,
        where: Mapping[str, Sequence[str]],
        reader: str | None,
        candidates: int,
    ) -> Lists:
        """The chunks nearest `vector` and the chunks `words` match, filtered alike.

        One read-only transaction, so both lists are of one state of the index.
        pgvector applies a `WHERE` after the HNSW scan, so a filter matching one
        chunk in ten would keep about four of the forty it reads.
        `hnsw.iterative_scan = relaxed_order` (pgvector 0.8.0 and later) keeps
        the scan going until the list is full or the index is exhausted (R19.4
        row 7). Empty when nothing has been prepared yet.
        """
        with self._session(f"searching index {index!r}") as connection:
            column = self._embedding_column(connection)
            if column is None:
                return Lists()
            self._register(connection)
            as_vector = HalfVector if column.startswith("halfvec") else Vector
            filters, values = _filters(where, reader)
            params = {
                "index": index,
                "vector": as_vector(list(vector)),
                "words": words,
                "candidates": candidates,
                **values,
            }
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                connection.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
                nearest = connection.execute(
                    self._sql(_NEAREST, filters=filters), params
                ).fetchall()
                matching = connection.execute(
                    self._sql(_MATCHING, filters=filters), params
                ).fetchall()
        documents: dict[str, Described] = {}
        return Lists(
            meaning=_candidates(nearest, documents),
            words=_candidates(matching, documents),
            documents=dict(sorted(documents.items())),
        )


def _filters(
    where: Mapping[str, Sequence[str]], reader: str | None
) -> tuple[sql.Composable, dict[str, object]]:
    """The conditions both lists are filtered by, and the parameters they are bound to.

    A document's carried value is a JSON string or a JSON array of strings
    (R18.9). `?|` finds a value as either, so one condition serves both, and
    the values of one field are one choice (R19.4 row 4). A field the document
    does not carry is `NULL`, which matches nothing.
    """
    conditions: list[sql.Composable] = []
    values: dict[str, object] = {}
    for at, (field, wanted) in enumerate(sorted(where.items())):
        conditions.append(
            sql.SQL(" AND (d.filter_values -> {field}::text) ?| {wanted}::text[]").format(
                field=sql.Placeholder(f"field_{at}"), wanted=sql.Placeholder(f"wanted_{at}")
            )
        )
        values[f"field_{at}"] = field
        values[f"wanted_{at}"] = list(wanted)
    if reader is not None:
        # The chunk's own readers, put there so no join can lose them (R18.6).
        conditions.append(sql.SQL(" AND %(reader)s = ANY(c.acl)"))
        values["reader"] = reader
    return sql.SQL("").join(conditions), values


def _candidates(
    rows: Sequence[tuple], documents: dict[str, Described]
) -> tuple[Candidate, ...]:
    """One list's rows as candidates, each one's document described once in `documents`."""
    found: list[Candidate] = []
    for chunk_id, document_id, kind, heading_path, text, title, carried in rows:
        found.append(Candidate(chunk_id, document_id, kind, tuple(heading_path), text))
        documents.setdefault(document_id, Described(document_id, title, dict(carried)))
    return tuple(found)
