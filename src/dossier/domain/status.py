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
class Owed:
    """A document a sync still owes its source: its fetch failed (R2.23, R17.2)."""

    key: str
    failed_at: datetime
    error: str


@dataclass(frozen=True)
class Held:
    """What the ledger holds for one source (R17.1), and what it is owed (R17.2)."""

    active: int
    tombstoned: int
    last_synced: datetime | None
    owed: tuple[Owed, ...] = ()

    @classmethod
    def of(
        cls,
        states: Iterable[State],
        *,
        last_synced: datetime | None,
        owed: tuple[Owed, ...] = (),
    ) -> Held:
        """Counted from the states of a source's ledger rows.

        A tombstoned row is counted apart rather than dropped: it is a document
        that left, and a run that pinned it still resolves it (R2.7).
        """
        counted = Counter(states)
        return cls(
            active=counted[State.ACTIVE],
            tombstoned=counted[State.TOMBSTONED],
            last_synced=last_synced,
            owed=owed,
        )


def source_lines(declared: Sequence[str], held: Mapping[str, Held]) -> list[str]:
    """One line per source, in the order `sources.yaml` declares them (R17.1).

    A declared source the ledger has never seen is `never synced`, with no
    counts: `0 held` would say a sync ran and found nothing. A source the ledger
    holds and `sources.yaml` no longer declares comes after, by id, and says so.
    Its documents are still held, and the runs that pinned them still resolve
    them (R2.7), so leaving it out would hide them.
    """
    lines: list[str] = []
    for source in declared:
        if source in held:
            lines += _held_lines(source, held[source])
        else:
            lines.append(f"{source} · never synced")
    for source in sorted(set(held) - set(declared)):
        first, *owed = _held_lines(source, held[source])
        lines += [f"{first} · not in sources.yaml", *owed]
    return lines


def _held_lines(source: str, holding: Held) -> list[str]:
    """The source's line, then one beneath it for each document it is owed (R17.2)."""
    return [
        f"{source} · {holding.active} held · {holding.tombstoned} tombstoned"
        f" · last synced {_instant(holding.last_synced)}",
        *(
            f"  owed {owed.key}, since {_instant(owed.failed_at)}: {owed.error}"
            for owed in sorted(holding.owed, key=lambda owed: owed.key)
        ),
    ]


def _instant(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
