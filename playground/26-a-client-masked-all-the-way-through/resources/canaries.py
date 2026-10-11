"""The seven canaries of `specs/_fixtures.md`, and a search for them in any text.

Every value is fictional, and chosen so that it can be searched for. A masked
pipeline shows a model none of them, and records none of them anywhere but
on this machine. The other scripts here import this list, so there is one.
"""

from __future__ import annotations

CANARIES = (
    "Erika Mustermann",
    "Hans Muster",
    "erika.mustermann@example.ch",
    "+41 44 555 01 23",
    "CH93 0076 2011 6238 5295 7",
    "756.1234.5678.97",
    "CIF 0042-118733",
)


def held(text: str) -> list[str]:
    """The canaries `text` holds, case folded and with its line breaks read as spaces.

    `ERIKA MUSTERMANN` is the client too, and a value wrapped across two lines
    is still the value.
    """
    flat = " ".join(text.split()).casefold()
    return [value for value in CANARIES if value.casefold() in flat]
