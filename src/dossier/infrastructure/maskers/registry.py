"""Which masker a declaration's `masker:` means, from the entry points (spec 021).

A masker is found by the name an installed package registers it under, as a
converter is (R8.7). None is installed by default: `presidio` comes with the
`masking` extra, and a declaration naming a masker nothing provides is refused
before any model is asked (R21.7 row 2).
"""

from __future__ import annotations

from importlib.metadata import entry_points

from dossier.domain.masking import MaskingDeclaration
from dossier.domain.ports import Masker

ENTRY_POINT_GROUP = "dossier.maskers"


class UnknownMasker(ValueError):
    """A declaration names a masker no installed package provides."""


def installed_maskers() -> list[str]:
    return sorted(point.name for point in entry_points(group=ENTRY_POINT_GROUP))


def masker_for(declaration: MaskingDeclaration) -> Masker:
    """The masker `declaration` names, built with it."""
    for point in entry_points(group=ENTRY_POINT_GROUP):
        if point.name == declaration.masker:
            return point.load()(declaration)
    available = ", ".join(installed_maskers()) or "none"
    raise UnknownMasker(
        f"masker {declaration.masker!r} is provided by no installed package "
        f"(installed: {available}). Install it: uv sync --extra masking"
    )
