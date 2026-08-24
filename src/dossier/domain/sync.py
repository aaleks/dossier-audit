"""The decisions incremental sync is made of (spec 002).

Pure functions over values the caller already holds. Nothing here fetches,
reads a file, or asks the clock what time it is -- that is what lets the sync
rules be proved in milliseconds with a plain dict.
"""

from __future__ import annotations

import json

# Canonical JSON: keys sorted, no incidental whitespace, escaped to ASCII. Every
# one of those three is a hash-stability decision rather than a style choice --
# R5.6 rules out relying on dict order, on a platform's default separators, or on
# how a given Python version happens to encode a non-ASCII character.
_CANONICAL = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": True}


def normalise(payload: bytes, *, fields: list[str] | None) -> bytes:
    """The bytes to hash for `payload`, given the source's declared projection.

    With no declared fields the payload is returned untouched: there is nothing
    to project onto, and every byte of it is content (R2.10). With fields, the
    payload is parsed as JSON and reduced to those keys in canonical form, so
    that a field the pipeline never reads cannot report the item as changed
    (R2.2).

    The stored snapshot is always the raw payload. This exists only to decide
    what the content hash is computed over.
    """
    if fields is None:
        return payload

    if not fields:
        # An empty list is a projection onto nothing, which no payload satisfies.
        # Reading it as "hash everything" would hand a source the exact opposite
        # of what it declared, silently (R3.9).
        raise ValueError(
            "fields is empty: a projection onto no fields matches nothing. "
            "Omit `fields` entirely to hash the payload as received (R2.10)."
        )

    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        # Deferred here on purpose: load time never fetches a payload, so it
        # cannot know whether one is structured (R3.9 counter-example).
        raise ValueError(
            f"a projection onto {sorted(fields)} needs a JSON payload, and this one "
            f"does not parse: {error}"
        ) from error

    if not isinstance(document, dict):
        raise ValueError(
            f"a projection onto {sorted(fields)} needs a JSON object, "
            f"got {type(document).__name__}"
        )

    # `in` rather than `.get`, so that an absent field stays absent. An absent
    # field and one explicitly set to null mean different things to a source
    # system, and collapsing them would make two different items hash alike.
    projected = {name: document[name] for name in sorted(fields) if name in document}
    return json.dumps(projected, **_CANONICAL).encode()
