"""The shape of what the ledger remembers (spec 002).

One row per item per source. A value object, not storage -- where these rows live
is `dossier.infrastructure.ledger`'s business, and keeping the shape here lets
the sync decisions be tested without one.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from dossier.domain.sync import State


class LedgerRow(BaseModel):
    """What is held for one item, at which remote version and content hash."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    key: str
    remote_version: str | None
    content_hash: str
    # What the connector said these bytes are (R2.16). Recorded rather than
    # re-derived: conversion may not re-fetch to ask (R0.1), and a name on disk
    # is not evidence about content (R8.3).
    media_type: str
    snapshot_path: str
    first_seen: datetime
    last_seen: datetime
    state: State = State.ACTIVE

    def content(self) -> tuple:
        """Everything about this row except when it was last observed.

        R2.9 claims two syncs over an unchanged source produce identical ledger
        content apart from `last_seen` and `last_sync_at`. This is that claim
        made comparable: `first_seen` is included because it is written once and
        never rewritten, so an identical sync must not move it either.
        """
        return (
            self.source_id,
            self.key,
            self.remote_version,
            self.content_hash,
            self.media_type,
            self.snapshot_path,
            self.first_seen,
            self.state,
        )
