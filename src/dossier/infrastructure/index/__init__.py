"""Writing and searching the embedding index (specs 018 and 019).

The fourth package left of the hash boundary (R0.16): the index is a Postgres
server, reached over the network. The `IndexSink` port it implements reads back
only the ids and content hashes of the documents an index holds, to write only
what changed (R18.4), so nothing the index holds enters a key, a manifest or a
score. `IndexSearch`, a port of its own, reads back what the index is for --
chunks, their text, their documents' titles and values -- and what it reads
reaches the terminal and MLflow, and nothing else (R0.17).

`psycopg` and `pgvector` are the `index` extra, imported only here. `connect`
and `connect_search` import them when an index is first needed, so a `dossier`
installed without the extra still loads, and is told which extra to install
when it is asked to write or search an index.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dossier.infrastructure.index.postgres import PostgresIndexSearch, PostgresIndexSink


class IndexSinkFailed(RuntimeError):
    """The index could not be reached, or refused what it was asked to hold."""


class IndexSearchFailed(RuntimeError):
    """The index could not be reached, or could not answer what a search asked."""


def connect(dsn: str) -> PostgresIndexSink:
    """A sink writing to the Postgres index at `dsn`, or `IndexSinkFailed` naming the extra.

    Nothing is reached yet: the connection is opened by the first thing asked.
    """
    try:
        from dossier.infrastructure.index.postgres import PostgresIndexSink
    except ImportError as error:
        raise IndexSinkFailed(
            "writing an index needs `psycopg` and `pgvector`, which are not installed. "
            "Install the extra -- pip install 'dossier[index]'."
        ) from error
    return PostgresIndexSink(dsn)


def connect_search(dsn: str) -> PostgresIndexSearch:
    """A search of the Postgres index at `dsn`, or `IndexSearchFailed` naming the extra.

    Nothing is reached yet: the connection is opened by the first thing asked.
    """
    try:
        from dossier.infrastructure.index.postgres import PostgresIndexSearch
    except ImportError as error:
        raise IndexSearchFailed(
            "searching an index needs `psycopg` and `pgvector`, which are not installed. "
            "Install the extra -- pip install 'dossier[index]'."
        ) from error
    return PostgresIndexSearch(dsn)
