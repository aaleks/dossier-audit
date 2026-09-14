"""Finding the providers a model identifier may name (R9.1).

Resolution is by entry point, never by a match statement, for the reason
R1.7 gives for connectors: a `match provider` in the core would make every new
provider a change to code every existing pipeline depends on.
"""

from __future__ import annotations

from importlib.metadata import entry_points

ENTRY_POINT_GROUP = "dossier.models"


def available_providers() -> list[str]:
    """Every provider an installed package declares, sorted.

    Names only: nothing is imported and no client is built. Loading a pipeline
    asks this, and loading reaches no network and no model (R3.8, R0.9).
    """
    return sorted(point.name for point in entry_points(group=ENTRY_POINT_GROUP))
