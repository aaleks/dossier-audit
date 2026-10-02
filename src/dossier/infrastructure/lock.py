"""The workspace's lock: one command writes it at a time (R20.1).

The operating system's own lock on `.dossier/lock` -- `msvcrt.locking` on
Windows, `fcntl.flock` elsewhere -- which the system lets go when the process
ends, however it ends. A command killed mid-run leaves nothing to clean up,
which a lock file made with `O_EXCL` would not: it outlives the command that
made it, and refuses every command after until a person deletes it.

Who holds it is in `.dossier/lock.json` beside it, not in the locked file: on
Windows a locked byte cannot be read by any other handle, this process's
included (probed).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import TracebackType

from dossier.domain.lock import held_line, holder

LOCK_PATH = Path(".dossier") / "lock"
HOLDER_PATH = Path(".dossier") / "lock.json"

# What each system raises when another handle holds the lock. Anything else --
# a filesystem with no locks at all, say -- is not another writer, and is not
# reported as one.
_HELD = (BlockingIOError, PermissionError)

if sys.platform == "win32":
    import msvcrt

    def _take(fd: int) -> None:
        # One byte, from where a new handle starts: the file stays empty, and
        # Windows locks past its end.
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _let_go(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _take(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _let_go(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class WorkspaceHeld(RuntimeError):
    """Another command holds the workspace. The message is the line to print (R20.1)."""


class WorkspaceLock:
    """Hold a workspace for one writer, or refuse at once: it never waits (R20.1)."""

    def __init__(self, workspace: Path, *, command: str, pid: int, since: datetime) -> None:
        self._workspace = workspace
        self._holder = holder(command=command, pid=pid, since=since)
        self._fd: int | None = None

    def __enter__(self) -> WorkspaceLock:
        path = self._workspace / LOCK_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            _take(fd)
        except _HELD:
            os.close(fd)
            raise WorkspaceHeld(held_line(_named(self._workspace / HOLDER_PATH))) from None
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        try:
            # Written in place rather than renamed into place: a refused command
            # may have the file open to read it, and Windows will not replace a
            # file another process has open. A reader that finds it half written
            # is refused without the details (row 6).
            (self._workspace / HOLDER_PATH).write_bytes(
                json.dumps(self._holder, sort_keys=True).encode("utf-8") + b"\n"
            )
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _let_go(fd)
        finally:
            os.close(fd)


def _named(path: Path) -> object:
    """The holder's record, or None when there is none to read yet."""
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
