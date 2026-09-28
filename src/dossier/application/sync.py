"""The sync use case (spec 002).

Orchestrates the decisions in `dossier.domain.sync` over a connector, a store and
a ledger. It takes all three as arguments and constructs none of them, which is
what lets the whole use case run against fakes.

Nothing here decides anything either. What needs fetching, what counts as
changed, which items have left scope and where the window starts are all domain
functions; this module is the order they happen in.

An item and the files attached to it are handled the same way, because they are
the same kind of thing: an address to fetch, hash and record (R1.6, R2.6). The
only thing an attachment does not share with its item is the projection -- a PDF
has no fields to project onto.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from dossier.domain.hashing import content_hash
from dossier.domain.ledger import LedgerRow
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import Connector, ItemRef, LedgerWriter, SnapshotWriter
from dossier.domain.store import snapshot_path
from dossier.domain.sync import (
    Change,
    Repointed,
    Returned,
    State,
    classify,
    configured_overlap,
    listing_hash,
    listing_is_complete,
    must_refetch,
    needs_fetch,
    normalise,
    owed_items,
    projection_changed,
    reactivated,
    repointed,
    source_config_hash,
    sync_window,
    tombstones,
)


@dataclass(frozen=True)
class SourceReport:
    """What one source cost this sync (R2.13)."""

    source_id: str
    known: int = 0
    changed: int = 0
    new: int = 0
    fetched: int = 0
    snapshots_written: int = 0
    tombstoned: int = 0
    failed: tuple[str, ...] = ()
    # Each failed key with the error its source gave. A failure is not zero
    # work, so it is reported with what went wrong rather than only counted
    # (R2.13 row 4, R1.9).
    failures: tuple[tuple[str, str], ...] = ()
    # Each changed item with the address it held and the one it holds now, in
    # key order. The count says how many moved; a person needs which, and from
    # what, to open the two and diff them (R2.18).
    repointed: tuple[Repointed, ...] = ()
    # Each key this sync tombstoned, in key order: the item absent from a full
    # listing (R2.7) and the file its item no longer carries (R2.6 row 3) alike.
    # `1 tombstoned` says something left and not what (R2.20).
    departed: tuple[str, ...] = ()
    # Each key a listing offered again after it was tombstoned, in key order:
    # neither known nor new, and counted as neither (R2.25).
    returned: tuple[Returned, ...] = ()
    # Why the listing failed, if it did. The source is then left as a listing
    # that never finished leaves it, and the sources after it still sync
    # (R2.27).
    listing_failed: str | None = None


@dataclass(frozen=True)
class SyncReport:
    """What the whole sync cost."""

    sources: list[SourceReport] = field(default_factory=list)

    @property
    def snapshots_written(self) -> int:
        return sum(report.snapshots_written for report in self.sources)

    @property
    def tombstoned(self) -> int:
        return sum(report.tombstoned for report in self.sources)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(key for report in self.sources for key in report.failed)


# The artifact a sync's MLflow run carries, naming what the terminal named (R11.6).
CHANGES_NAME = "changes.json"


def changes_artifact(reports: Sequence[SourceReport]) -> bytes:
    """`changes.json`: every item the sync repointed, revived or tombstoned, by
    source (R11.6, R11.24).

    Composed from the reports' own lists -- the ones the terminal printed -- and
    never from a second reading of the ledger, so the record and the terminal
    cannot disagree. Sources are ordered by id and keys are already sorted, so
    the bytes do not depend on the order the sources happened to run in (R0.4).
    An empty sync is every list empty, not a missing file: an absent artifact is
    indistinguishable from a sync that never ran (R11.4 row 3).
    """
    ordered = sorted(reports, key=lambda report: report.source_id)
    record = {
        "changed": [
            {"source": report.source_id, "key": item.key, "from": item.held, "to": item.now}
            for report in ordered
            for item in report.repointed
        ],
        # An item back unchanged carries no addresses, as its line prints none;
        # one back with other bytes carries both, as its line does (R2.25).
        "returned": [
            {"source": report.source_id, "key": item.key}
            | ({"from": item.moved.held, "to": item.moved.now} if item.moved else {})
            for report in ordered
            for item in report.returned
        ],
        "tombstoned": [
            {"source": report.source_id, "key": key}
            for report in ordered
            for key in report.departed
        ],
    }
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()


@dataclass(frozen=True)
class _Target:
    """One addressable thing a sync stores: an item, or an attachment it carries.

    An attachment is fetched by its own key, hashed over its own bytes and kept
    in its own row (R1.6, spec 001). `fields` is the projection to hash under,
    and it is `None` for an attachment: a projection describes an item's
    structured payload, and a PDF hanging off it has nothing to project onto
    (R2.10).
    """

    key: str
    remote_version: str | None
    fields: list[str] | None
    is_item: bool
    item_key: str | None = None


@dataclass(frozen=True)
class _Stored:
    """What handling one target cost, in the terms `SourceReport` counts."""

    fetched: int = 0
    changed: int = 0
    new: int = 0
    written: int = 0
    failure: tuple[str, str] | None = None
    repointed: Repointed | None = None


def sync_source(
    *,
    config: SourceConfig,
    connector: Connector,
    store: SnapshotWriter,
    ledger: LedgerWriter,
    now: datetime,
    full: bool = False,
) -> SourceReport:
    """Bring one source up to date, and say what that cost.

    `full` asks the source for everything regardless of its watermark (R2.22):
    the one way to tombstone what a source that narrows its listings has
    dropped, short of editing `fields` to force a re-evaluation.
    """
    started_at = now

    # A projection the recorded hashes were not computed under makes every one
    # of them an answer to a different question, so every item is evaluated
    # again (R2.3). So does a change to what the connector's fetch asks for
    # (R2.26); a connector declaring nothing asks for nothing beyond an item's
    # address. `None` is a source that has never synced: nothing to
    # invalidate, and the normal path already fetches everything.
    configured = source_config_hash(config, fetch_asks=getattr(connector, "fetch_asks", ""))
    reevaluating = projection_changed(
        recorded=ledger.config_hash(config.id), configured=configured
    )

    # Keys of the source's own that its last listing did not answer -- an
    # `export:` added, a query narrowed -- make this listing complete, so what
    # they change is seen now rather than at the next `--full` (R2.24). An
    # unrecorded hash, from a ledger written before it was kept, vouches for
    # nothing and lists whole once.
    listed_under = listing_hash(config)
    rescoped = ledger.listing_hash(config.id) != listed_under

    # The source's own overlap where it set one (R2.4, "configurable per source"):
    # a key the loader accepts and sync then ignores is configuration that lies.
    since = sync_window(
        reevaluating=reevaluating,
        last_sync_at=ledger.watermark(config.id),
        overlap=configured_overlap(config.watermark_overlap),
        full=full,
        rescoped=rescoped,
    )

    # Tombstoning may only be computed against a complete listing (R1.3, R2.7):
    # one sync asked for whole, or one from a connector that never narrows.
    # Deciding from `since` alone believed a folder on its first sync and
    # never again, and a deleted file stayed active for ever (R1.11, R2.21).
    complete = listing_is_complete(since=since, lists_everything=connector.lists_everything)

    held = {row.key: row for row in ledger.rows(config.id)}
    known = sum(1 for row in held.values() if row.state is State.ACTIVE)

    listed: set[str] = set()
    departed_files: set[str] = set()
    changed = new = fetched = written = 0
    failed: list[str] = []
    failures: list[tuple[str, str]] = []
    moved: list[Repointed] = []
    returned: list[Returned] = []

    # What earlier syncs failed to fetch, and are owed (R2.23). Read before the
    # listing, because this sync settles and adds to it as it goes.
    owed = ledger.owed(config.id)
    owed_keys = {key for key, _ in owed}
    visited: set[str] = set()
    # Why the listing stopped, when it did not finish (R2.27).
    listing_failed: list[str] = []

    def listed_then_owed() -> Iterator[ItemRef]:
        """The listing, then the items owed keys hang off that it did not return.

        A generator so the owed items are decided only once the listing is
        exhausted, and `visited` holds everything it returned. An item owed only
        for a file keeps its recorded marker, so it is not fetched unless its own
        fetch is owed too (R2.1).
        """
        refs = iter(connector.list(since))
        while True:
            # Only the listing's own failure is caught here. One raised while an
            # item is stored is the store's, and a failed fetch is R1.9's.
            try:
                listed_ref = next(refs)
            except StopIteration:
                break
            except Exception as error:
                # A listing that did not finish answers nothing about what it
                # did not reach: no owed item is asked for, and nothing held
                # is tombstoned (R2.27).
                listing_failed.append(str(error))
                return
            visited.add(listed_ref.key)
            yield listed_ref
        for item, item_owed in owed_items(owed, visited=visited, complete=complete):
            recorded = held.get(item)
            yield ItemRef(
                key=item,
                remote_version=None
                if item_owed or recorded is None
                else recorded.remote_version,
                updated_at=None,
            )

    for ref in listed_then_owed():
        # Asked for every listed item, changed or not: an issue's own version
        # marker says nothing about the PDF hanging off it, and R2.6 is exactly
        # the case where the item is untouched and the attachment is not.
        attached = tuple(connector.attachments(ref.key))

        for target in (
            _Target(ref.key, ref.remote_version, config.fields, True),
            *(_Target(a.key, a.remote_version, None, False, ref.key) for a in attached),
        ):
            listed.add(target.key)
            recorded = held.get(target.key)
            outcome = _store(
                target,
                config=config,
                connector=connector,
                store=store,
                ledger=ledger,
                recorded=recorded,
                now=now,
                force_fetch=must_refetch(reevaluating=reevaluating, is_item=target.is_item),
            )
            fetched += outcome.fetched
            written += outcome.written
            if (
                recorded is not None
                and recorded.state is State.TOMBSTONED
                and outcome.failure is None
            ):
                # Back from tombstoned: not known before this sync, and not new
                # to the ledger. Its bytes may have changed while it was gone,
                # and then it carries both addresses rather than counting as a
                # change to something that was known (R2.25).
                returned.append(Returned(key=target.key, moved=outcome.repointed))
            else:
                changed += outcome.changed
                new += outcome.new
                if outcome.repointed is not None:
                    moved.append(outcome.repointed)
            if outcome.failure is not None:
                failed.append(outcome.failure[0])
                failures.append(outcome.failure)
                # Owed until it is stored, whether or not the next listing
                # returns its item (R2.23).
                ledger.owe(
                    config.id,
                    target.key,
                    item_key=target.item_key,
                    at=now,
                    error=outcome.failure[1],
                )
            elif target.key in owed_keys:
                ledger.settle(config.id, [target.key])

        # A file owed but no longer carried is owed nothing: there is nothing
        # left to fetch, and nothing held to tombstone (R2.23 row 4).
        carried = {attachment.key for attachment in attached}
        ledger.settle(
            config.id,
            [key for key, item_key in owed if item_key == ref.key and key not in carried],
        )

        departed_files |= _settle_attachments(
            item_key=ref.key,
            listed={attachment.key for attachment in attached},
            held=held,
            config=config,
            ledger=ledger,
        )

    departed_keys: set[str] = set(departed_files)
    finished = not listing_failed
    if complete and finished:
        active = {key for key, row in held.items() if row.state is State.ACTIVE}
        # The files just tombstoned are already handled. `held` was read before
        # this sync, so without them here they would be counted a second time.
        already = {
            key for key, row in held.items() if row.state is State.TOMBSTONED
        } | departed_files

        departed = tombstones(
            held=active,
            listed=listed,
            already_tombstoned=already,
            listing_was_complete=complete,
        )
        ledger.set_state(config.id, departed, State.TOMBSTONED)
        departed_keys |= set(departed)

        # A complete listing answers for every item: what it left out is gone,
        # and what that item was owed is owed no longer (R2.23 row 5).
        ledger.settle(
            config.id, [key for key, item_key in owed if (item_key or key) not in listed]
        )

    # Whatever listing offered it, windowed or complete, an item that came back
    # is in scope again (R2.7 row 3). Deciding this only against a complete
    # listing left an item that came back unchanged in a windowed one tombstoned.
    ledger.set_state(config.id, sorted(item.key for item in returned), State.ACTIVE)

    if not failed and finished:
        # R2.8: a partial sync must not be mistaken for a complete one, so the
        # watermark only advances when every item was handled.
        ledger.set_watermark(config.id, started_at)
        # Recorded for the same reason and at the same moment: a re-evaluation
        # that failed partway must be retried, not remembered as done (R2.3).
        ledger.set_config_hash(config.id, configured)

    # Recorded once a listing under these keys has run to the end, failed
    # fetches or not: what a failed key is owed is kept by the ledger itself
    # (R2.23), and the listing's own question has been answered (R2.24).
    if finished:
        ledger.set_listing_hash(config.id, listed_under)

    return SourceReport(
        source_id=config.id,
        known=known,
        changed=changed,
        new=new,
        fetched=fetched,
        snapshots_written=written,
        tombstoned=len(departed_keys),
        returned=tuple(sorted(returned, key=lambda item: item.key)),
        failed=tuple(failed),
        failures=tuple(failures),
        # Sorted here rather than where it is printed: a connector lists in
        # whatever order it likes, and the report is what the tracker records
        # as well as what the terminal shows (R11.6).
        repointed=tuple(sorted(moved, key=lambda item: item.key)),
        departed=tuple(sorted(departed_keys)),
        listing_failed=listing_failed[0] if listing_failed else None,
    )


def _store(
    target: _Target,
    *,
    config: SourceConfig,
    connector: Connector,
    store: SnapshotWriter,
    ledger: LedgerWriter,
    recorded: LedgerRow | None,
    now: datetime,
    force_fetch: bool,
) -> _Stored:
    """Bring one address up to date: fetch it if it moved, store it if it changed."""
    if not force_fetch and not needs_fetch(
        recorded_version=recorded.remote_version if recorded else None,
        listed_version=target.remote_version,
    ):
        ledger.touch(config.id, target.key, seen_at=now)
        return _Stored()

    try:
        payload = connector.fetch(target.key)
    except Exception as error:
        # R1.9: the ledger is left untouched for this item. A partial sync
        # must never record something it did not successfully store.
        return _Stored(failure=(target.key, str(error)))

    digest = content_hash(normalise(payload.payload, fields=target.fields))
    outcome = classify(
        recorded_hash=recorded.content_hash if recorded else None,
        computed_hash=digest,
    )

    if not outcome.writes_snapshot:
        ledger.touch(config.id, target.key, seen_at=now)
        return _Stored(fetched=1)

    # Asked before storing, because `put` is idempotent: two sources holding
    # identical bytes share one snapshot, and the second is not a write
    # (R2.11 example 2).
    #
    # At the payload's own hash, not at `digest`: the normalised hash only
    # decides whether the item changed, and for a source declaring `fields`
    # it addresses a projection nothing ever stores (R2.17).
    stored = content_hash(payload.payload)
    already_held = store.exists(stored)
    store.put(payload.payload)

    ledger.record(
        LedgerRow(
            source_id=config.id,
            key=target.key,
            # Which item carries this file, so that what it attaches to is a
            # recorded fact rather than something inferred from its key (R2.6).
            item_key=target.item_key,
            remote_version=target.remote_version,
            content_hash=digest,
            # What the connector said these bytes are, recorded once here
            # because nothing downstream may work it out again (R2.16).
            media_type=payload.media_type,
            snapshot_path=snapshot_path(stored),
            first_seen=recorded.first_seen if recorded else now,
            last_seen=now,
            state=State.ACTIVE,
        )
    )
    return _Stored(
        fetched=1,
        changed=int(outcome is Change.CHANGED),
        new=int(outcome is Change.NEW),
        written=0 if already_held else 1,
        repointed=repointed(
            key=target.key,
            outcome=outcome,
            previous=recorded.snapshot_path if recorded else None,
            stored=stored,
        ),
    )


def _settle_attachments(
    *,
    item_key: str,
    listed: set[str],
    held: dict[str, LedgerRow],
    config: SourceConfig,
    ledger: LedgerWriter,
) -> set[str]:
    """Tombstone the files this item no longer carries, and revive any that returned.

    Computed per item rather than from the source's listing, and it is the one
    place tombstoning does not need a full listing: `attachments(key)` answers
    for that item completely, even during an incremental sync. A file removed
    from an issue is therefore a departure now rather than at the next full
    listing (R2.6 row 3).
    """
    files = {key: row for key, row in held.items() if row.item_key == item_key}
    already = {key for key, row in files.items() if row.state is State.TOMBSTONED}

    departed = tombstones(
        held={key for key, row in files.items() if row.state is State.ACTIVE},
        listed=listed,
        already_tombstoned=already,
    )
    ledger.set_state(config.id, departed, State.TOMBSTONED)

    # A file that came back goes active again, as an item does (R2.7 example 3).
    ledger.set_state(
        config.id, reactivated(listed=listed, already_tombstoned=already), State.ACTIVE
    )
    return set(departed)
