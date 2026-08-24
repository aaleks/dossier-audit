"""The decisions incremental sync is made of (spec 002).

Pure functions over values the caller already holds. Nothing here fetches,
reads a file, or asks the clock what time it is -- that is what lets the sync
rules be proved in milliseconds with a plain dict.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

# Clock skew between dossier and the source, plus source-side indexing lag, are
# both routinely minutes and occasionally hours. A day of overlap costs a handful
# of redundant listings; getting it wrong costs a document that is never fetched
# again, and which nobody notices because there is no error to see (R2.4).
DEFAULT_OVERLAP = timedelta(hours=24)

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


def window_start(
    last_sync_at: datetime | None, *, overlap: timedelta = DEFAULT_OVERLAP
) -> datetime | None:
    """The `since` to pass to `Connector.list`, given a source's watermark.

    Returns `None` when the source has never synced: there is no watermark to
    subtract from, and a full listing is wanted anyway -- it is what tombstoning
    is computed against (R1.3, R2.7).
    """
    if overlap <= timedelta(0):
        # Zero is the boundary the rule names: "never from last_sync_at". A
        # source configuring `watermark_overlap: 0h` is asking for exactly the
        # sync that skips its own edge, and it should hear about it now rather
        # than lose an item quietly.
        raise ValueError(
            f"watermark_overlap must be positive, got {overlap}. "
            "Sync asks from last_sync_at minus an overlap, never from "
            "last_sync_at itself (R2.4)."
        )

    if last_sync_at is None:
        return None

    if last_sync_at.tzinfo is None:
        # A naive watermark means something different on every machine that
        # reads it, and an hour of drift here is an item silently not fetched.
        raise ValueError(
            f"last_sync_at must be timezone-aware, got naive {last_sync_at.isoformat()}"
        )

    return last_sync_at - overlap


def needs_fetch(*, recorded_version: str | None, listed_version: str | None) -> bool:
    """Whether an item's payload must be requested, given its version markers.

    The only way to skip a fetch is for the source to vouch that nothing moved:
    both markers present and exactly equal (R2.1). Everything else fetches, and
    the content hash then decides whether anything is actually stored (R2.2) --
    so a fetch is not a write, and over-fetching costs a request rather than a
    snapshot.

    `recorded_version` is `None` both for an item with no ledger row and for one
    whose source has no version marker at all. The two are different situations
    and the same answer: there is nothing to compare, so fetch.
    """
    if recorded_version is None or listed_version is None:
        return True

    # Compared verbatim. A version marker is an opaque token belonging to the
    # source system; normalising case or whitespace would mean guessing at
    # another system's semantics, and a wrong guess is a change that is never
    # fetched again -- silently, because there is no error to see.
    return recorded_version != listed_version
