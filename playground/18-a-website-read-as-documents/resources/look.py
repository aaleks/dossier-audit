#!/usr/bin/env python3
"""Read what a workspace holds, for exercise 18. Run it from inside the workspace.

    look.py ledger [SOURCE]         every document, its marker, media type and state
    look.py payload SOURCE/KEY      the path of the snapshot the ledger holds for KEY
    look.py note SOURCE/KEY         the note a stage reads for KEY
    look.py watermarks              where each source's next sync will ask from

A document is named by its source and its key, `uv-projects/index`: all three
sites in this exercise have a page keyed `index` (R1.30).

It only reads. The ledger is SQLite, the snapshots and the converted artifacts
are files, and none of it needs `dossier` to be read. Not part of `dossier`, and
nothing under `src/` or `tests/` imports it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

STATE = Path(".dossier")


def main(argv: list[str]) -> int:
    if not (STATE / "ledger.db").is_file():
        print("no .dossier/ledger.db here: run this from inside the workspace", file=sys.stderr)
        return 2
    command, *rest = argv or ["ledger"]
    commands = {"ledger": ledger, "payload": payload, "note": note, "watermarks": watermarks}
    if command not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    return commands[command](*rest)


def _db() -> sqlite3.Connection:
    return sqlite3.connect(STATE / "ledger.db")


def ledger(source: str | None = None) -> int:
    rows = _db().execute(
        "select source_id, key, remote_version, media_type, state from items "
        "where ? is null or source_id = ? order by source_id, key",
        (source, source),
    )
    for source_id, key, marker, media_type, state in rows:
        print(f"{source_id:12} {key:34} {marker or '-':26} {media_type:10} {state}")
    return 0


def _snapshot(document: str) -> str:
    """The address of the snapshot the ledger holds for `source/key`, as `ab/cd/<hash>`."""
    source, _, key = document.partition("/")
    row = (
        _db()
        .execute(
            "select snapshot_path from items where source_id = ? and key = ?", (source, key)
        )
        .fetchone()
    )
    if row is None:
        raise SystemExit(f"the ledger holds no document {key!r} from {source!r}")
    return row[0]


def payload(document: str) -> int:
    print((STATE / "snapshots" / _snapshot(document)).as_posix())
    return 0


def note(document: str) -> int:
    """The note converted from the snapshot `source/key` holds.

    Found by the snapshot's address, which the `.meta.json` beside each artifact
    names: a convert key is composed from the snapshot and the converter, never
    from the document's key (R5.4).
    """
    held = _snapshot(document).rsplit("/", 1)[-1]
    for meta in sorted((STATE / "cache" / "convert").rglob("*.meta.json")):
        if json.loads(meta.read_text(encoding="utf-8")).get("snapshot") == held:
            # The bytes as the converter wrote them. Printed as text, Windows
            # would turn every newline into two bytes.
            sys.stdout.buffer.write(
                meta.with_name(meta.name.removesuffix(".meta.json")).read_bytes()
            )
            return 0
    print(f"{document} has not been converted: run `dossier convert site-audit` first")
    return 1


def watermarks() -> int:
    for source, at in _db().execute("select * from watermarks order by source_id"):
        print(f"{source:12} {at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
