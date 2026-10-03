"""How each index was last written, recorded on this machine (spec 021, R21.18).

`.dossier/index/<index>.json` names the masker a masked index was written
with, or `null` for an unmasked one. It is here rather than in the index
because the index port reads back nothing but ids and content hashes (R0.19):
an embed that asked Postgres whether its rows were masked would widen what
crosses the hash boundary. Local file IO, not network.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dossier.domain.resolution import PinnedMasker

INDEX_RECORDS = Path(".dossier") / "index"


def written_masked(workspace: Path, index: str) -> bool | None:
    """Whether `index` was last written masked, or `None` when no record says."""
    path = workspace / INDEX_RECORDS / f"{index}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("masker") is not None


def record_written(workspace: Path, index: str, masker: PinnedMasker | None) -> None:
    """Record how `index` was just written, whole or not at all."""
    directory = workspace / INDEX_RECORDS
    directory.mkdir(parents=True, exist_ok=True)
    body = {"masker": None if masker is None else masker.model_dump()}
    path = directory / f"{index}.json"
    # Beside it, then renamed over it: a rename is all or nothing, so a killed
    # embed leaves the last record whole rather than half of a new one.
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
