"""What `dossier status` says about a workspace, decided from what it holds (spec 017).

Every function here takes what was read -- the ledger's counts, the runs'
manifests, a calibration -- and returns the lines `status` prints. The reading
is `dossier.application.status`'s; nothing here opens a file.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from dossier.domain.sync import State


@dataclass(frozen=True)
class Held:
    """What the ledger holds for one source (R17.1)."""

    active: int
    tombstoned: int
    last_synced: datetime | None

    @classmethod
    def of(cls, states: Iterable[State], *, last_synced: datetime | None) -> Held:
        """Counted from the states of a source's ledger rows.

        A tombstoned row is counted apart rather than dropped: it is a document
        that left, and a run that pinned it still resolves it (R2.7).
        """
        counted = Counter(states)
        return cls(
            active=counted[State.ACTIVE],
            tombstoned=counted[State.TOMBSTONED],
            last_synced=last_synced,
        )


def source_lines(declared: Sequence[str], held: Mapping[str, Held]) -> list[str]:
    """One line per source, in the order `sources.yaml` declares them (R17.1).

    A declared source the ledger has never seen is `never synced`, with no
    counts: `0 held` would say a sync ran and found nothing. A source the ledger
    holds and `sources.yaml` no longer declares comes after, by id, and says so.
    Its documents are still held, and the runs that pinned them still resolve
    them (R2.7), so leaving it out would hide them.
    """
    lines = [
        _held_line(source, held[source]) if source in held else f"{source} · never synced"
        for source in declared
    ]
    lines += [
        f"{_held_line(source, held[source])} · not in sources.yaml"
        for source in sorted(set(held) - set(declared))
    ]
    return lines


def _held_line(source: str, holding: Held) -> str:
    return (
        f"{source} · {holding.active} held · {holding.tombstoned} tombstoned"
        f" · last synced {_instant(holding.last_synced)}"
    )


def _instant(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
