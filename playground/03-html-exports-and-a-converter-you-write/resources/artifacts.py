#!/usr/bin/env python3
"""Every converted artifact in a workspace: which document, which converter, what it holds.

Run it from the workspace, after `dossier convert`:

    python ../../03-html-exports-and-a-converter-you-write/resources/artifacts.py
    python .../artifacts.py PLAY-4001            # only rows mentioning PLAY-4001
    python .../artifacts.py PLAY-4003 --cat      # and print what each one holds

An artifact is stored under its convert key, `.dossier/cache/convert/ab/cd/<key>`,
with a `.meta.json` beside it naming the snapshot and the converter that made it
(R0.3). That record is what lets you go from a key back to a document, and this
script does nothing but follow it: it reads the cache and the ledger, and writes
nothing.

The `sha256` column is the hash of the artifact's *bytes*, which is not its
key. Two artifacts with different keys and the same `sha256` are two conversions
that wrote the same text -- and the text is what a step's key is computed over
(spec 005), so a step asked about one is served from cache for the other.

Standard library only; not part of `dossier`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

CACHE = Path(".dossier/cache/convert")
LEDGER = Path(".dossier/ledger.db")


def main(argv: list[str]) -> int:
    show = "--cat" in argv
    wanted = [arg for arg in argv if arg != "--cat"]
    if not LEDGER.exists():
        print("no .dossier/ledger.db here: run this from the workspace, after a sync")
        return 2

    ledger = sqlite3.connect(LEDGER)
    # Every revision a key has had, so an artifact of an older snapshot still
    # has a name after the document changed.
    names = dict(ledger.execute("select content_hash, key from revisions"))
    names.update(ledger.execute("select content_hash, key from items"))

    rows = []
    for meta in CACHE.rglob("*.meta.json"):
        record = json.loads(meta.read_text(encoding="utf-8"))
        artifact = meta.with_name(meta.name.removesuffix(".meta.json"))
        body = artifact.read_bytes()
        key = names.get(record["snapshot"], record["snapshot"][:12])
        line = (
            key,
            record["converter_id"],
            record["converter_version"],
            record["snapshot"][:8],
            len(body),
            hashlib.sha256(body).hexdigest()[:12],
            artifact,
        )
        if all(any(w in str(field) for field in line[:3]) for w in wanted):
            rows.append(line)

    for key, converter, version, snapshot, size, digest, artifact in sorted(rows):
        print(
            f"{key:41} snapshot {snapshot}  {converter:19} {version:6} "
            f"{size:>5} bytes  sha256 {digest}"
        )
        if show:
            print(f"  {artifact.as_posix()}")
            text = artifact.read_bytes().decode("utf-8", errors="replace")
            print("\n".join(f"    {line}" for line in text.splitlines()) or "    (nothing)")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
