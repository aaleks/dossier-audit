"""Which chunker an index's `chunker.name` means, from the entry points (R18.1).

A chunker is found by the name an installed package registers it under, as a
converter is (R8.7), so a new way of cutting documents is never an edit to the
core. Its settings are the declaration's, checked when the index loads.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from dossier.domain.index import ChunkerSettings
from dossier.domain.ports import Chunker

ENTRY_POINT_GROUP = "dossier.chunkers"


class UnknownChunker(ValueError):
    """An index names a chunker no installed package provides."""


def installed_chunkers() -> list[str]:
    return sorted(point.name for point in entry_points(group=ENTRY_POINT_GROUP))


def chunker_for(settings: ChunkerSettings) -> Chunker:
    """The chunker `settings` names, built with them."""
    for point in entry_points(group=ENTRY_POINT_GROUP):
        if point.name == settings.name:
            return point.load()(max_chars=settings.max_chars)
    available = ", ".join(installed_chunkers()) or "none"
    raise UnknownChunker(
        f"chunker {settings.name!r} is provided by no installed package. Available: {available}"
    )
