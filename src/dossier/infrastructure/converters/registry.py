"""Finding the converters an installation provides (R8.7).

Resolution is by entry point, never by a match statement -- the same mechanism
and the same reasoning as connectors (R1.7). A new converter is a package that
declares one in the `dossier.converters` group; it is never an edit to a file
under `src/dossier/`.

That matters more for converters than for connectors. A PDF converter is a large
dependency with its own release cadence, and pinning every pipeline in existence
to it because it lives in the core package is exactly the coupling this avoids.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from dossier.domain.ports import Converter

ENTRY_POINT_GROUP = "dossier.converters"


def installed_converters() -> list[Converter]:
    """Every converter an installed package provides, in a stable order.

    Sorted by the pair each one claims. `entry_points()` returns whatever order
    the environment produces, and an ordering that varies between machines is
    the sort of thing that makes a cache hit in one place and miss in another
    (R5.6) -- even where, as here, a pair matches at most one converter.
    """
    found = [point.load()() for point in entry_points(group=ENTRY_POINT_GROUP)]
    return sorted(found, key=lambda converter: (converter.media_type, converter.kind))
