"""R17.2 — a source names each document a sync still owes it, with when its
fetch failed and why.

A key whose fetch failed is recorded as owed, and asked for again at the next
sync (R2.23). It is the only trace a failed fetch leaves, since the key's own
ledger row is left untouched (R1.9), so it is what `status` can say about a
sync that went wrong. R2.23 row 1's export is the example.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from dossier.domain.status import Held, Owed, source_lines

SYNCED = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
# The ledger as it was before R2.23: no `owed` table, and `items` without the
# `item_key` column R2.6 added.
OLDER_SCHEMA = """
CREATE TABLE items (
    source_id TEXT NOT NULL, key TEXT NOT NULL, remote_version TEXT,
    content_hash TEXT NOT NULL, media_type TEXT NOT NULL, snapshot_path TEXT NOT NULL,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, state TEXT NOT NULL,
    PRIMARY KEY (source_id, key)
);
CREATE TABLE watermarks (source_id TEXT PRIMARY KEY, last_sync_at TEXT NOT NULL);
"""
REFUSED = "GET https://wiki.example.internal/spaces/flyingpdf/pdfpageexport.action answered 403"


def lines_for(*owed: Owed) -> list[str]:
    held = Held(active=3, tombstoned=0, last_synced=SYNCED, owed=owed)
    return source_lines(["procedures-confluence"], {"procedures-confluence": held})


class TestStatusNamesWhatASyncStillOwes:
    """R17.2 — every owed document, under its source, with when and why."""

    def test_an_owed_document_is_named_under_its_source(self):
        """Row 1 — the one where `81920114.pdf` was refused `403`."""
        lines = lines_for(Owed(key="81920114.pdf", failed_at=SYNCED, error=REFUSED))

        assert lines == [
            "procedures-confluence · 3 held · 0 tombstoned · last synced 2026-08-06T09:00:00Z",
            f"  owed 81920114.pdf, since 2026-08-06T09:00:00Z: {REFUSED}",
        ]

    def test_each_owed_document_has_a_line_of_its_own_by_key(self):
        """Row 2 — the one owed an attachment and an export, handed over out of order."""
        lines = lines_for(
            Owed(key="INC-4821/report.pdf", failed_at=SYNCED, error="timed out"),
            Owed(key="81920114.pdf", failed_at=SYNCED, error=REFUSED),
        )

        assert [line.split(",")[0] for line in lines[1:]] == [
            "  owed 81920114.pdf",
            "  owed INC-4821/report.pdf",
        ]

    def test_nothing_owed_prints_no_owed_line(self):
        """Row 3, counter-example — the one whose last sync fetched everything."""
        assert len(lines_for()) == 1

    def test_a_ledger_from_before_owed_existed_is_read_as_it_is(self, tmp_path: Path):
        """Row 4, counter-example — the one written before R2.23, with no `owed` table.

        Opening it as `Ledger` does would add the table and the columns it lacks:
        a write, from a command that promises none (R17.5). So it is read as it
        is, and what it cannot hold is nothing owed.
        """
        from dossier.infrastructure.ledger import LEDGER_PATH, read_held

        path = tmp_path / LEDGER_PATH
        path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as older:
            older.executescript(OLDER_SCHEMA)
            older.execute(
                "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "procedures-confluence",
                    "OPS-115",
                    "v12",
                    "sha256:c4d1",
                    "text/html",
                    "snapshots/c4/d1",
                    SYNCED.isoformat(),
                    SYNCED.isoformat(),
                    "active",
                ),
            )
            older.execute(
                "INSERT INTO watermarks VALUES (?, ?)",
                ("procedures-confluence", SYNCED.isoformat()),
            )
            older.commit()
        before = path.read_bytes()

        held = read_held(tmp_path)

        assert held == {
            "procedures-confluence": Held(active=1, tombstoned=0, last_synced=SYNCED)
        }
        assert path.read_bytes() == before
