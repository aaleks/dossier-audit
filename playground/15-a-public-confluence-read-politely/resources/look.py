#!/usr/bin/env python3
"""Read what a workspace holds, for exercise 15. Run it from inside the workspace.

    look.py ledger                 every document, its marker, media type and state
    look.py note KEY               the note a stage reads for KEY
    look.py payload KEY            the path of the snapshot the ledger holds for KEY
    look.py revisions KEY          every snapshot KEY has held, oldest first
    look.py ground KEY SPAN        whether SPAN is found in KEY's note, as a run decides it
    look.py watermarks             where each source's next sync will ask from
    look.py owed                   each key whose fetch failed, and is asked again (R2.23)

It only reads. The ledger is SQLite, the snapshots and the converted artifacts
are files, and none of it needs `dossier` to be read -- except `ground`, which
imports the function a run uses (`locate_span`, R6.4), because a check written
here instead would be a second opinion about grounding, not the run's.

Not part of `dossier`, and nothing under `src/` or `tests/` imports it.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

STATE = Path(".dossier")
# What a `page_images` artifact starts with: a container of parts, not text (R8.11).
PARTS = b"DOSSIER-PARTS"


def main(argv: list[str]) -> int:
    if not (STATE / "ledger.db").is_file():
        print("no .dossier/ledger.db here: run this from inside the workspace", file=sys.stderr)
        return 2
    command, *rest = argv or ["ledger"]
    commands = {
        "ledger": ledger,
        "note": note,
        "payload": payload,
        "revisions": revisions,
        "ground": ground,
        "watermarks": watermarks,
        "owed": owed,
    }
    if command not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    return commands[command](*rest)


def _db() -> sqlite3.Connection:
    return sqlite3.connect(STATE / "ledger.db")


def ledger() -> int:
    rows = _db().execute(
        "select source_id, key, remote_version, media_type, state from items "
        "order by source_id, key"
    )
    for source, key, marker, media_type, state in rows:
        print(f"{source:15} {key:32} {marker or '-':20} {media_type:45} {state}")
    return 0


def _snapshot(key: str) -> str:
    """The address of the snapshot the ledger holds for `key`, as `ab/cd/<hash>`."""
    row = _db().execute("select snapshot_path from items where key = ?", (key,)).fetchone()
    if row is None:
        raise SystemExit(f"the ledger holds no document keyed {key!r}")
    return row[0]


def payload(key: str) -> int:
    print((STATE / "snapshots" / _snapshot(key)).as_posix())
    return 0


def revisions(key: str) -> int:
    rows = _db().execute(
        "select recorded_at, snapshot_path from revisions where key = ? order by recorded_at",
        (key,),
    )
    for recorded_at, path in rows:
        print(f"{recorded_at}  .dossier/snapshots/{path}")
    return 0


def _note(key: str) -> bytes | None:
    """The text artifact converted from the snapshot `key` holds, or None if it has none.

    A `.meta.json` beside each artifact names the snapshot it was made from, so
    the note is found by the snapshot's address, not by the document's key: the
    convert key is composed from the snapshot and the converter, never the key
    (R5.4).
    """
    held = _snapshot(key).rsplit("/", 1)[-1]
    for meta in sorted((STATE / "cache" / "convert").rglob("*.meta.json")):
        if json.loads(meta.read_text(encoding="utf-8")).get("snapshot") != held:
            continue
        artifact = meta.with_name(meta.name.removesuffix(".meta.json")).read_bytes()
        if not artifact.startswith(PARTS):
            return artifact
    return None


def note(key: str) -> int:
    artifact = _note(key)
    if artifact is None:
        print(f"{key} has no text artifact: it converted to page_images, or not at all")
        return 1
    # The bytes as the converter wrote them. Printed as text, Windows would
    # turn every newline into two bytes, and a note saved from here would no
    # longer be the note the cache holds.
    sys.stdout.buffer.write(artifact)
    return 0


def ground(key: str, span: str) -> int:
    from dossier.domain.grounding import locate_span

    artifact = _note(key)
    if artifact is None:
        print(f"{key} has no text artifact to search")
        return 1
    found = locate_span(span, document_text=artifact.decode("utf-8"))
    print(f"{'grounded' if found else 'ungrounded'}  {key}  {span!r}")
    return 0 if found else 1


def watermarks() -> int:
    for source, at in _db().execute("select * from watermarks order by source_id"):
        print(f"{source:15} {at}")
    return 0


def owed() -> int:
    """What the ledger is owed: each key whose fetch failed, until it is stored.

    A failed fetch leaves the key's own row as it was, or absent (R1.9), so this
    table is the only record that the failure happened. The item beside each key
    is the one a sync visits to ask for it again, listed or not (R2.23). The time
    is the latest failure, rewritten each time the key is asked and refused.
    """
    rows = _db().execute(
        "select source_id, key, item_key, failed_at from owed order by source_id, key"
    )
    for source, key, item, failed_at in rows:
        print(f"{source:15} {key:16} carried by {item or key:10} last failed {failed_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
