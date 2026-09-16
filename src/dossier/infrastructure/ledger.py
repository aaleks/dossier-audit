"""Where the ledger rows live (spec 002).

SQLite under `.dossier/ledger.db` (R0.8). One row per item per source, plus a
watermark per source.

Nothing here decides anything. Which items need fetching, what counts as changed
and which have left scope are all decisions in `dossier.domain.sync`; this module
remembers the answers.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from dossier.domain.ledger import LedgerRow
from dossier.domain.sync import State

LEDGER_PATH = ".dossier/ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    source_id      TEXT NOT NULL,
    key            TEXT NOT NULL,
    remote_version TEXT,
    content_hash   TEXT NOT NULL,
    media_type     TEXT NOT NULL,
    snapshot_path  TEXT NOT NULL,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    state          TEXT NOT NULL,
    PRIMARY KEY (source_id, key)
);

CREATE TABLE IF NOT EXISTS watermarks (
    source_id    TEXT PRIMARY KEY,
    last_sync_at TEXT NOT NULL
);

-- The projection each source's recorded hashes were computed under (R2.3). A
-- table of its own rather than a column on `watermarks`: `CREATE TABLE IF NOT
-- EXISTS` gives an existing ledger the new table for free, where a new column
-- would need a migration for state that is regenerable anyway.
CREATE TABLE IF NOT EXISTS source_config (
    source_id   TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL
);
"""


class Ledger:
    """What is held, at which remote version and content hash."""

    def __init__(self, workspace: Path) -> None:
        self._path = Path(workspace) / LEDGER_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def rows(self, source_id: str) -> list[LedgerRow]:
        """Every row for a source, ordered by key.

        Ordered because an unordered read is machine-dependent, and R2.9 compares
        ledger content between two syncs.
        """
        cursor = self._connection.execute(
            "SELECT * FROM items WHERE source_id = ? ORDER BY key", (source_id,)
        )
        return [_to_row(record) for record in cursor.fetchall()]

    def sources(self) -> list[str]:
        """Every source the ledger holds rows for, in a stable order.

        Sorted, because a caller looking a key up across sources would otherwise
        find it under whichever source the query happened to return first.
        """
        cursor = self._connection.execute("SELECT DISTINCT source_id FROM items")
        return sorted(record[0] for record in cursor.fetchall())

    def row(self, source_id: str, key: str) -> LedgerRow | None:
        cursor = self._connection.execute(
            "SELECT * FROM items WHERE source_id = ? AND key = ?", (source_id, key)
        )
        record = cursor.fetchone()
        return _to_row(record) if record else None

    def record(self, row: LedgerRow) -> None:
        """Write a row, preserving `first_seen` if the item is already known.

        `first_seen` answers "since when have we held this", which a later sync
        cannot change without lying. R2.7 example 3 depends on it surviving an
        item leaving scope and coming back.
        """
        self._connection.execute(
            """
            INSERT INTO items (source_id, key, remote_version, content_hash,
                               media_type, snapshot_path, first_seen, last_seen,
                               state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_id, key) DO UPDATE SET
                remote_version = excluded.remote_version,
                content_hash   = excluded.content_hash,
                media_type     = excluded.media_type,
                snapshot_path  = excluded.snapshot_path,
                last_seen      = excluded.last_seen,
                state          = excluded.state
            """,
            (
                row.source_id,
                row.key,
                row.remote_version,
                row.content_hash,
                row.media_type,
                row.snapshot_path,
                _to_text(row.first_seen),
                _to_text(row.last_seen),
                row.state.value,
            ),
        )
        self._connection.commit()

    def touch(self, source_id: str, key: str, *, seen_at: datetime) -> None:
        """Record that an unchanged item was observed again.

        The one write an unchanged item causes. R2.5 counts snapshots written,
        not ledger touches -- an item can be seen without anything being stored.
        """
        self._connection.execute(
            "UPDATE items SET last_seen = ? WHERE source_id = ? AND key = ?",
            (_to_text(seen_at), source_id, key),
        )
        self._connection.commit()

    def set_state(self, source_id: str, keys: Iterable[str], state: State) -> None:
        self._connection.executemany(
            "UPDATE items SET state = ? WHERE source_id = ? AND key = ?",
            [(state.value, source_id, key) for key in keys],
        )
        self._connection.commit()

    def watermark(self, source_id: str) -> datetime | None:
        cursor = self._connection.execute(
            "SELECT last_sync_at FROM watermarks WHERE source_id = ?", (source_id,)
        )
        record = cursor.fetchone()
        return _from_text(record["last_sync_at"]) if record else None

    def config_hash(self, source_id: str) -> str | None:
        """The projection this source's recorded hashes were computed under (R2.3).

        `None` for a source that has never synced, which is not a mismatch:
        there are no recorded hashes for a changed projection to invalidate.
        """
        cursor = self._connection.execute(
            "SELECT config_hash FROM source_config WHERE source_id = ?", (source_id,)
        )
        record = cursor.fetchone()
        return record["config_hash"] if record else None

    def set_config_hash(self, source_id: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO source_config (source_id, config_hash) VALUES (?, ?)
            ON CONFLICT (source_id) DO UPDATE SET config_hash = excluded.config_hash
            """,
            (source_id, value),
        )
        self._connection.commit()

    def set_watermark(self, source_id: str, when: datetime) -> None:
        self._connection.execute(
            """
            INSERT INTO watermarks (source_id, last_sync_at) VALUES (?, ?)
            ON CONFLICT (source_id) DO UPDATE SET last_sync_at = excluded.last_sync_at
            """,
            (source_id, _to_text(when)),
        )
        self._connection.commit()


def _to_row(record: sqlite3.Row) -> LedgerRow:
    return LedgerRow(
        source_id=record["source_id"],
        key=record["key"],
        remote_version=record["remote_version"],
        content_hash=record["content_hash"],
        media_type=record["media_type"],
        snapshot_path=record["snapshot_path"],
        first_seen=_from_text(record["first_seen"]),
        last_seen=_from_text(record["last_seen"]),
        state=State(record["state"]),
    )


def _to_text(when: datetime) -> str:
    """ISO 8601 in UTC, always.

    A naive or locally-offset timestamp would read back differently depending on
    the machine, and R2.9 compares ledger content across syncs (R0.4).
    """
    if when.tzinfo is None:
        raise ValueError(f"refusing to store a naive timestamp: {when!r}")
    return when.astimezone(UTC).isoformat()


def _from_text(text: str) -> datetime:
    return datetime.fromisoformat(text)
