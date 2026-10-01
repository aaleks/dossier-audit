"""Writing the embedding index (spec 018).

The fourth package left of the hash boundary (R0.16): the index is a Postgres
server, reached over the network. The `IndexSink` port it implements reads back
only the ids and content hashes of the documents an index holds, to write only
what changed (R18.4), so nothing the index holds enters a key, a manifest or a
score.

`psycopg` and `pgvector` are the `index` extra, imported only here. `connect`
imports them when an index is first needed, so a `dossier` installed without
the extra still loads, and is told which extra to install when it is asked to
write an index.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dossier.infrastructure.index.postgres import PostgresIndexSink


class IndexSinkFailed(RuntimeError):
    """The index could not be reached, or refused what it was asked to hold."""


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
