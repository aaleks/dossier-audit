"""Who holds the workspace, and what a second writer is told (R20.1).

The lock itself is the operating system's (`dossier.infrastructure.lock`); this
is the record a holder leaves beside it, and the line a refused command prints
from it. The record follows the lock, so a refused command can find it missing,
cut off, or not a record at all -- and is refused all the same, without the
details (row 6). The lock is what refuses; the record only says who.
"""

from __future__ import annotations

from datetime import UTC, datetime

WRITING = "another dossier command is writing this workspace"
AGAIN = "Try again when it has finished"


def holder(*, command: str, pid: int, since: datetime) -> dict[str, object]:
    """The record a writer leaves once it holds the lock: what, which process, since when."""
    stamp = f"{since.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"
    return {"command": command, "pid": pid, "since": stamp}


def held_line(record: object) -> str:
    """The one line a second writer prints: the holder, when the record names one."""
    if isinstance(record, dict):
        command, pid, since = record.get("command"), record.get("pid"), record.get("since")
        # `bool` is an `int` to Python, and `true` is no process id.
        if (
            isinstance(command, str)
            and isinstance(pid, int)
            and not isinstance(pid, bool)
            and isinstance(since, str)
        ):
            return f"{WRITING}: {command}, pid {pid}, since {since}. {AGAIN}"
    return f"{WRITING}. {AGAIN}"
