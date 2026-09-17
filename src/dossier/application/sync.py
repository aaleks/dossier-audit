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

from dataclasses import dataclass, field
from datetime import datetime

from dossier.domain.hashing import content_hash
from dossier.domain.ledger import LedgerRow
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import Connector, LedgerWriter, SnapshotWriter
from dossier.domain.store import snapshot_path
from dossier.domain.sync import (
    Change,
    State,
    classify,
    configured_overlap,
    must_refetch,
    needs_fetch,
    normalise,
    projection_changed,
    reactivated,
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


def sync_source(
    *,
    config: SourceConfig,
    connector: Connector,
    store: SnapshotWriter,
    ledger: LedgerWriter,
    now: datetime,
) -> SourceReport:
    """Bring one source up to date, and say what that cost."""
    started_at = now

    # A projection the recorded hashes were not computed under makes every one
    # of them an answer to a different question, so every item is evaluated
    # again (R2.3). `None` is a source that has never synced: nothing to
    # invalidate, and the normal path already fetches everything.
    configured = source_config_hash(config)
    reevaluating = projection_changed(
        recorded=ledger.config_hash(config.id), configured=configured
    )

    # The source's own overlap where it set one (R2.4, "configurable per source"):
    # a key the loader accepts and sync then ignores is configuration that lies.
    since = sync_window(
        reevaluating=reevaluating,
        last_sync_at=ledger.watermark(config.id),
        overlap=configured_overlap(config.watermark_overlap),
    )

    # Tombstoning may only be computed against a full listing (R1.3, R2.7).
    listing_is_complete = since is None

    held = {row.key: row for row in ledger.rows(config.id)}
    known = sum(1 for row in held.values() if row.state is State.ACTIVE)

    listed: set[str] = set()
    departed_files: set[str] = set()
    changed = new = fetched = written = 0
    failed: list[str] = []
    failures: list[tuple[str, str]] = []

    for ref in connector.list(since):
        # Asked for every listed item, changed or not: an issue's own version
        # marker says nothing about the PDF hanging off it, and R2.6 is exactly
        # the case where the item is untouched and the attachment is not.
        attached = tuple(connector.attachments(ref.key))

        for target in (
            _Target(ref.key, ref.remote_version, config.fields, True),
            *(_Target(a.key, a.remote_version, None, False, ref.key) for a in attached),
        ):
            listed.add(target.key)
            outcome = _store(
                target,
                config=config,
                connector=connector,
                store=store,
                ledger=ledger,
                recorded=held.get(target.key),
                now=now,
                force_fetch=must_refetch(reevaluating=reevaluating, is_item=target.is_item),
            )
            fetched += outcome.fetched
            changed += outcome.changed
            new += outcome.new
            written += outcome.written
            if outcome.failure is not None:
                failed.append(outcome.failure[0])
                failures.append(outcome.failure)

        departed_files |= _settle_attachments(
            item_key=ref.key,
            listed={attachment.key for attachment in attached},
            held=held,
            config=config,
            ledger=ledger,
        )

    tombstoned = len(departed_files)
    if listing_is_complete:
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
            listing_was_complete=listing_is_complete,
        )
        ledger.set_state(config.id, departed, State.TOMBSTONED)
        tombstoned += len(departed)

        returned = reactivated(listed=listed, already_tombstoned=already)
        ledger.set_state(config.id, returned, State.ACTIVE)

    if not failed:
        # R2.8: a partial sync must not be mistaken for a complete one, so the
        # watermark only advances when every item was handled.
        ledger.set_watermark(config.id, started_at)
        # Recorded for the same reason and at the same moment: a re-evaluation
        # that failed partway must be retried, not remembered as done (R2.3).
        ledger.set_config_hash(config.id, configured)

    return SourceReport(
        source_id=config.id,
        known=known,
        changed=changed,
        new=new,
        fetched=fetched,
        snapshots_written=written,
        tombstoned=tombstoned,
        failed=tuple(failed),
        failures=tuple(failures),
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
