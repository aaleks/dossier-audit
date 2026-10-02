# 020 — Running it every day

**Status:** Proposed
**Rules:** R20.1

## Purpose

Spec 015's flow is "cron (daily)". A job a team relies on runs beside people,
and beside itself when a run outlasts the day. Nothing stopped two commands
from writing one workspace at once: `gc --apply` beside a `run` deleted entries
the run was writing and no manifest named yet (spec 016 said so), two `sync`s
wrote one ledger, and `embed` read a run's records while `run` wrote them
(analysis_v2, §3.4). This spec makes the workspace one writer's at a time.

## The lock

A command that writes the workspace holds its lock from before it reads
anything to its end:

| Takes the lock | Does not |
|---|---|
| `sync`, `convert`, `run` (a try and a replay included), `embed`, `gc --apply`, `review apply` | `status`, `search`, `run --plan`, `gc` without `--apply`, `eval`, `calibrate`, `review pull`, `dataset publish`, `prompts publish` |

The right-hand column writes no ledger, snapshot, run, stage or convert entry,
index row or gold file. `eval` and `calibrate` write the judge cache, whose
entries are written whole (R5.8) and which `gc` never collects (R16.3 row 6).

A second writer is refused at once, naming the first, and exits 2, as a
mistake in the workspace does. It never waits: a cron job refused fails
plainly and runs again next time, and a person sees who holds the workspace
and since when. Decided by `a.aleks` on 2026-10-02, against waiting a while
before refusing.

The lock is the operating system's own, on `.dossier/lock`: `msvcrt.locking`
on Windows, `fcntl.flock` elsewhere. The system releases it when the process
ends however it ends, so a command killed mid-run leaves no lock behind and
nothing to clean up. Who holds it, with the process id and when it started, is
in `.dossier/lock.json` beside it, written once the lock is held: on Windows a
locked byte cannot be read by another process, so the details cannot sit in
the locked file.

The details follow the lock, so for a moment a writer holds the workspace and
`lock.json` does not yet name it: the file is missing on a workspace's first
lock, and names the writer before otherwise. A command refused in that moment
is refused all the same, and a missing or unreadable `lock.json` refuses it
without the details (row 6). The lock is what refuses; the file only says who.

## Existing options considered

| Option | Covers | Decision |
|---|---|---|
| `filelock` (Unlicense; the lock `virtualenv` and `pip` use) | A cross-platform lock file, with timeouts | Not adopted: refusing at once needs none of its waiting, and the two system calls it wraps are in the standard library. No dependency |
| A lock file created with `O_EXCL` | Works on every filesystem | Rejected: a command killed while holding it leaves the file, and every command after it is refused until a person deletes it |

## Must hold

### R20.1 — a command that writes the workspace holds its lock, and a second one is refused at once, naming the first

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.lock.held_line`), infrastructure (`dossier.infrastructure.lock.WorkspaceLock`), cli
- **Proved by:** `tests/integration/test_R020_1__a_second_writer_is_refused.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` holding the workspace, pid 4120, since `2026-10-02T07:30:12Z`; `dossier sync incident-audit` started beside it | exit 2, before anything is read: `another dossier command is writing this workspace: run, pid 4120, since 2026-10-02T07:30:12Z. Try again when it has finished`; nothing synced |
| 2 | the same, `dossier gc --apply` | refused the same way; nothing deleted |
| 3 | *counter-example* — the same, `dossier status`, `dossier run incident-audit --plan` or `dossier gc` without `--apply` | each runs as before: none of them writes the workspace |
| 4 | *counter-example* — the run killed, its process gone | the next writer takes the lock: the system released it with the process |
| 5 | *counter-example* — `dossier sync incident-audit`, then `dossier run incident-audit`, one after the other | both run: a command lets the lock go when it ends |
| 6 | the lock held and `.dossier/lock.json` missing, or not the details a writer leaves | refused the same way, exit 2, without them: `another dossier command is writing this workspace. Try again when it has finished` |
