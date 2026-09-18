"""The decisions incremental sync is made of (spec 002).

Pure functions over values the caller already holds. Nothing here fetches,
reads a file, or asks the clock what time it is -- that is what lets the sync
rules be proved in milliseconds with a plain dict.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from dossier.domain.hashing import content_hash, is_content_hash
from dossier.domain.pipeline import SourceConfig
from dossier.domain.store import held_address

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


def source_config_hash(config: SourceConfig) -> str:
    """The hash of what a source's configuration says about hashing its payloads (R2.3).

    The projection, and nothing else. `watermark_overlap` is deliberately absent:
    it decides what is *asked for*, never what a payload hashes to, so a source
    that widened its overlap has not changed what its recorded hashes mean, and
    re-fetching a corpus over it would be an afternoon's work for no answer
    (R2.3 row 4).

    The field list is treated as a set -- deduplicated and sorted before hashing
    -- because a projection is one: an author who reordered two lines has not
    changed their source. Declaring no `fields` at all is a different question
    from any projection, not the same question with an empty answer, so it
    hashes differently (R2.10).
    """
    projection = None if config.fields is None else sorted(set(config.fields))
    return content_hash(json.dumps({"fields": projection}, **_CANONICAL).encode())


def configured_overlap(configured: timedelta | None) -> timedelta:
    """The overlap a source asks for, or the default where it names none (R2.4).

    `is None`, not `or`: a configured `0h` is falsy, and replacing it with the
    default would turn a mistake the author made into a different overlap they
    never wrote. Passed through as it is, `window_start` refuses it by name.
    """
    return DEFAULT_OVERLAP if configured is None else configured


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


def projection_changed(*, recorded: str | None, configured: str) -> bool:
    """Whether the source's projection moved since its rows were hashed (R2.3).

    `None` is a source that has never synced: nothing to invalidate, and the
    normal path already fetches everything, so it is not a change.
    """
    return recorded is not None and recorded != configured


def sync_window(
    *, reevaluating: bool, last_sync_at: datetime | None, overlap: timedelta
) -> datetime | None:
    """Where this sync's listing starts: the watermark window, or everything (R2.3, R2.4).

    A re-evaluation asks for a full listing. An incremental one omits precisely
    the unchanged items whose hashes have to be recomputed, which would leave
    most of the source recorded under the old projection.
    """
    if reevaluating:
        return None
    return window_start(last_sync_at, overlap=overlap)


def listing_is_complete(*, since: datetime | None, lists_everything: bool) -> bool:
    """Whether this listing may be subtracted from (R2.21).

    Two ways to be complete: sync asked for everything, or the connector
    returns everything whatever it is asked (R1.11). Only the first counted
    before, so a folder -- which never narrows -- was believed on its first sync
    and never again, and a file deleted from it stayed `active` for ever. The
    third case, a windowed listing from a connector that narrows, is the one
    R2.7 row 4 forbids subtracting from: its omissions are unchanged items, not
    departures.
    """
    return since is None or lists_everything


def must_refetch(*, reevaluating: bool, is_item: bool) -> bool:
    """Whether a target is fetched whatever its version says (R2.3).

    A changed projection re-evaluates the items it describes. An attachment is
    hashed over its own bytes, so no projection can change what its recorded
    hash means, and it is fetched only when its version says to (R1.6, R2.6).
    """
    return reevaluating and is_item


# Servers that compare change times in their own timezone -- Jira reads
# `updated >= "2026-08-04 09:00"` in the server's, which is not knowable from
# here -- are asked from a day earlier. No timezone is more than a day from
# UTC, so the answer is a superset whatever the offset, which is the one kind
# of error R1.4 permits and R2.4's overlap does not already cover.
SERVER_ZONE_SLACK = timedelta(days=1)


def server_zone_floor(since: datetime, *, slack: timedelta = SERVER_ZONE_SLACK) -> datetime:
    """Where to ask a server that compares change times in its own zone (R1.4)."""
    return since - slack


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


class Change(Enum):
    """What a sync decided about one item (R2.2).

    `writes_snapshot` lives on the outcome rather than at the call site. R2.5
    counts snapshots written, and a caller deciding for itself which outcomes
    write would be a second implementation of this rule -- one that can disagree
    with this one.
    """

    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"

    @property
    def writes_snapshot(self) -> bool:
        return self is not Change.UNCHANGED


def classify(*, recorded_hash: str | None, computed_hash: str) -> Change:
    """What to do with an item, given the hash held and the hash just computed.

    Both hashes are over the *normalised* payload (R2.10), never over the raw
    bytes -- which is what stops a regenerated HTML field reporting every item as
    changed on every sync.
    """
    if not is_content_hash(computed_hash):
        raise ValueError(
            f"computed_hash {computed_hash!r} is not a content hash. "
            "Comparing display prefixes is how two different documents get "
            "called unchanged (R0.7)."
        )
    if recorded_hash is None:
        return Change.NEW
    if not is_content_hash(recorded_hash):
        raise ValueError(
            f"recorded_hash {recorded_hash!r} is not a content hash. "
            "A ledger row holds the full digest, never a display prefix (R0.7)."
        )
    return Change.UNCHANGED if recorded_hash == computed_hash else Change.CHANGED


@dataclass(frozen=True)
class Repointed:
    """One row moved from one snapshot address to another, named for a person (R2.18).

    `held` and `now` are snapshot addresses -- the raw payload's own hash, full
    length -- because those are the files someone can open and diff. The
    normalised `content_hash` that decided the change is deliberately not here:
    for a source declaring `fields` it addresses a projection nothing stored
    (R2.17).
    """

    key: str
    held: str
    now: str


def repointed(
    *, key: str, outcome: Change, previous: str | None, stored: str
) -> Repointed | None:
    """What a sync names about one item, given what `classify` decided.

    Only a change has two addresses to show. A new item has no previous one,
    and an unchanged item has nothing the count does not already say -- a first
    sync of 4,000 items that named each would print 4,000 lines (R2.18 rows 4
    and 5).
    """
    if outcome is not Change.CHANGED:
        return None
    if previous is None:
        raise ValueError(f"{key!r} classified as changed with no recorded snapshot to compare")
    return Repointed(key=key, held=held_address(previous), now=stored)


class State(Enum):
    """What a ledger row currently is (spec 002).

    There is no `deleted`. An item that leaves scope is tombstoned so that a run
    which pinned its snapshots still resolves (R2.7, R4.9).
    """

    ACTIVE = "active"
    TOMBSTONED = "tombstoned"


def tombstones(
    *,
    held: set[str],
    listed: set[str],
    already_tombstoned: set[str] = frozenset(),
    listing_was_complete: bool = True,
) -> tuple[str, ...]:
    """Which held items have left the source's scope, in key order.

    `held` is the active rows for one source; `listed` is what a full listing
    just returned. The answer is the difference -- items recorded as present that
    the source no longer offers.

    Sorted, and a tuple rather than a set. This layer's whole contract is
    determinism, and handing a set out of it exports an iteration order that
    varies with `PYTHONHASHSEED`. It reaches an `executemany` today, where the
    order happens not to matter -- but "happens not to matter" is a property of
    the current caller, not of the value (R0.4).
    """
    if not listing_was_complete:
        # An incremental listing legitimately omits everything that did not
        # change. Computing departures from it would tombstone the entire
        # unchanged majority of a source: the most destructive thing sync could
        # do, and it would look like it had worked (R1.3, R2.7).
        raise ValueError(
            "tombstoning must be computed against a full listing. "
            "An incremental listing omits unchanged items, which are not departures."
        )
    return tuple(sorted(set(held) - set(listed) - set(already_tombstoned)))


def reactivated(*, listed: set[str], already_tombstoned: set[str]) -> tuple[str, ...]:
    """Which tombstoned items the source is offering again, in key order.

    Returned alongside `tombstones` rather than left to the caller: an item that
    comes back must go to `active`, and a sync that only handled departures would
    leave the ledger permanently wrong about it (R2.7 example 3).

    Sorted for the same reason `tombstones` is.
    """
    return tuple(sorted(set(listed) & set(already_tombstoned)))


# How an aggregate step's single artifact is filed (spec 003). Reserved here
# rather than in `application`, because "which keys may a source hold" is a
# decision and the two places that care about it must not disagree.
RESERVED_KEY = "*"


class DocumentCollision(ValueError):
    """Two sources hold the same document key (R4.10).

    A `ValueError` because a caller can fix it -- by renaming a key, or by
    dropping one of the sources from the pipeline. The application turns it into
    a resolution failure, so nothing runs and no run directory appears (R4.1).
    """


def one_document_per_key(held: Mapping[str, Sequence[str]]) -> None:
    """Refuse a run where two sources both hold a key (R4.10).

    A key identifies a document: `source.document` names one (R6.3), a gold file
    is keyed by one, and a manifest pins one snapshot per key. Two sources
    holding `INC-4821` make all three untrue, and the previous behaviour --
    keeping whichever source `sources:` listed last -- produced an audit that
    covered one document and reported the other.

    Sorted throughout, so the message is the same on every machine and does not
    depend on the order the sources were declared or the ledger returned them
    (R0.4, R5.6).
    """
    reserved = [
        f"  {RESERVED_KEY}: reserved for an aggregate step's artifact (spec 003), "
        f"held by {source}"
        for source in sorted(held)
        if RESERVED_KEY in held[source]
    ]
    if reserved:
        raise DocumentCollision(
            "a source holds a reserved document key:\n"
            + "\n".join(reserved)
            + "\nRename it; `*` is how an aggregate step's own artifact is filed."
        )

    sources_by_key: dict[str, list[str]] = {}
    for source in sorted(held):
        for key in held[source]:
            sources_by_key.setdefault(key, []).append(source)

    collisions = {key: sources for key, sources in sources_by_key.items() if len(sources) > 1}
    if not collisions:
        return

    raise DocumentCollision(
        "a document key identifies one document, and these are held by more than "
        "one source:\n"
        + "\n".join(
            f"  {key}: {', '.join(sorted(sources))}"
            for key, sources in sorted(collisions.items())
        )
        + "\nRename one, or drop a source from this pipeline."
    )
