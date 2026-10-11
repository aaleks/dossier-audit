"""Print every masked view a workspace holds, and the mapping kept beside it.

    python views.py            # from the workspace

A view is a file under `.dossier/cache/mask/`, with its record beside it in a
`.meta.json`. Its mapping, placeholder to value, is the file at the same path
under `.dossier/cache/mask-values/` (R21.21). This prints, for each view, its
first line -- a note's heading, or a key read as words (R21.8) -- the language
it was read in, what its record counts, and its mapping.

Read-only. It prints the values, because it reads them on this machine, where
they already are.
"""

from __future__ import annotations

import json
from pathlib import Path

MASK = Path(".dossier/cache/mask")
VALUES = Path(".dossier/cache/mask-values")


def main() -> None:
    views = sorted(
        path for path in MASK.rglob("*") if path.is_file() and path.suffix != ".json"
    )
    shown = []
    for view in views:
        record = json.loads(
            view.with_name(view.name + ".meta.json").read_text(encoding="utf-8")
        )
        kept = VALUES / view.relative_to(MASK)
        mapping = json.loads(kept.read_text(encoding="utf-8")) if kept.is_file() else None
        first = view.read_text(encoding="utf-8").splitlines()[0]
        shown.append((first, view.name, record, mapping))
    for first, key, record, mapping in sorted(shown):
        counts = ", ".join(f"{name} {count}" for name, count in record["masked"].items())
        print(f"{first}")
        print(f"  {key[:12]}…  {record['language']}  masked: {counts or 'nothing'}")
        if not mapping:
            print("  mapping: " + ("not kept" if mapping is None else "empty"))
        for placeholder, value in sorted((mapping or {}).items()):
            print(f"  {placeholder:<18} {value}")
    print(f"{len(views)} views")


if __name__ == "__main__":
    main()
