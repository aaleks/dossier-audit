"""The sync use case (spec 002).

Orchestrates the decisions in `dossier.domain.sync` over a connector, a store and
a ledger. It takes all three as arguments and constructs none of them, which is
what lets the whole use case run against fakes.

Nothing here decides anything either. What needs fetching, what counts as
changed, which items have left scope and where the window starts are all domain
functions; this module is the order they happen in.
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
    needs_fetch,
    normalise,
    reactivated,
    tombstones,
    window_start,
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
    # The source's own overlap where it set one (R2.4, "configurable per source"):
    # a key the loader accepts and sync then ignores is configuration that lies.
    since = window_start(
        ledger.watermark(config.id), overlap=configured_overlap(config.watermark_overlap)
    )

    # Tombstoning may only be computed against a full listing (R1.3, R2.7).
    listing_is_complete = since is None

    held = {row.key: row for row in ledger.rows(config.id)}
    known = sum(1 for row in held.values() if row.state is State.ACTIVE)

    listed: set[str] = set()
    changed = new = fetched = written = 0
    failed: list[str] = []

    for ref in connector.list(since):
        listed.add(ref.key)
        recorded = held.get(ref.key)

        if not needs_fetch(
            recorded_version=recorded.remote_version if recorded else None,
            listed_version=ref.remote_version,
        ):
            ledger.touch(config.id, ref.key, seen_at=now)
            continue

        try:
            item = connector.fetch(ref.key)
        except Exception:
            # R1.9: the ledger is left untouched for this item. A partial sync
            # must never record something it did not successfully store.
            failed.append(ref.key)
            continue

        fetched += 1
        digest = content_hash(normalise(item.payload, fields=config.fields))
        outcome = classify(
            recorded_hash=recorded.content_hash if recorded else None,
            computed_hash=digest,
        )

        if not outcome.writes_snapshot:
            ledger.touch(config.id, ref.key, seen_at=now)
            continue

        # Asked before storing, because `put` is idempotent: two sources holding
        # identical bytes share one snapshot, and the second is not a write
        # (R2.11 example 2).
        already_held = store.exists(digest)
        store.put(item.payload)
        if not already_held:
            written += 1

        ledger.record(
            LedgerRow(
                source_id=config.id,
                key=ref.key,
                remote_version=ref.remote_version,
                content_hash=digest,
                # What the connector said these bytes are, recorded once here
                # because nothing downstream may work it out again (R2.16).
                media_type=item.media_type,
                snapshot_path=snapshot_path(digest),
                first_seen=recorded.first_seen if recorded else now,
                last_seen=now,
                state=State.ACTIVE,
            )
        )
        changed += outcome is Change.CHANGED
        new += outcome is Change.NEW

    tombstoned = 0
    if listing_is_complete:
        active = {key for key, row in held.items() if row.state is State.ACTIVE}
        already = {key for key, row in held.items() if row.state is State.TOMBSTONED}

        departed = tombstones(held=active, listed=listed, already_tombstoned=already)
        ledger.set_state(config.id, departed, State.TOMBSTONED)
        tombstoned = len(departed)

        returned = reactivated(listed=listed, already_tombstoned=already)
        ledger.set_state(config.id, returned, State.ACTIVE)

    if not failed:
        # R2.8: a partial sync must not be mistaken for a complete one, so the
        # watermark only advances when every item was handled.
        ledger.set_watermark(config.id, started_at)

    return SourceReport(
        source_id=config.id,
        known=known,
        changed=changed,
        new=new,
        fetched=fetched,
        snapshots_written=written,
        tombstoned=tombstoned,
        failed=tuple(failed),
    )
