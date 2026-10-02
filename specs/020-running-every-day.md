# 020 — Running it every day

**Status:** Partially implemented
**Rules:** R20.1 – R20.2

## Purpose

Spec 015's flow is "cron (daily)". A job a team relies on runs beside people,
and beside itself when a run outlasts the day. Nothing stopped two commands
from writing one workspace at once: `gc --apply` beside a `run` deleted entries
the run was writing and no manifest named yet (spec 016 said so), two `sync`s
wrote one ledger, and `embed` read a run's records while `run` wrote them
(analysis_v2, §3.4). This spec makes the workspace one writer's at a time.

A job that runs every day also runs across upgrades, and its records have to
say which `dossier` wrote them. Every manifest (R4.9) and every MLflow record
(R11.19) carries `dossier_version`, and it said `0.1.0` for every commit since
the first. An `eval` of one run, repeated months apart, could score twice
differently after a change to scoring, and nothing recorded said why
(analysis_v2, §3.4). This spec makes the version say which commit it was.

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

The lock's two files are the lock's, not a command's work. A command that takes
the lock and is then refused for another reason -- a tracking server nobody can
reach (R10.5), an experiment template it cannot fill (R11.28 row 3), a pin
naming no run (R16.6 row 3) -- has written them, and "nothing written" in those
rules means nothing of the workspace's: no ledger, snapshot, run, cache entry or
pin.

## The version

`dossier`'s version is derived from git by `hatch-vcs` when it is installed, and
`pyproject.toml` names none. A tag `v0.2.0` makes the commit it names `0.2.0`;
every other commit is a development release past the last tag, naming itself.
Decided by `a.aleks` on 2026-10-02, against bumping a number by hand, which is
the step every release forgets.

The version is fixed when `dossier` is installed, not when it runs. An editable
install runs the source as it is, so a commit made after `uv sync` runs under
the version of the one before it until the next `uv sync`, which rebuilds the
install whenever the commit or a tag has moved (`[tool.uv] cache-keys`). R0.18
already asks for a `uv sync` after every pull. A source with no git history to
read, such as GitHub's zip of a commit, refuses to build, naming the variable
that gives it a version (`SETUPTOOLS_SCM_PRETEND_VERSION`), rather than
inventing one.

The version is in no key (R0.5 row 5), so a new one moves no cache.

## Existing options considered

| Option | Covers | Decision |
|---|---|---|
| `filelock` (Unlicense; the lock `virtualenv` and `pip` use) | A cross-platform lock file, with timeouts | Not adopted: refusing at once needs none of its waiting, and the two system calls it wraps are in the standard library. No dependency |
| A lock file created with `O_EXCL` | Works on every filesystem | Rejected: a command killed while holding it leaves the file, and every command after it is refused until a person deletes it |
| `hatch-vcs` (MIT; hatchling's plugin over `setuptools-scm`, which pip and pytest version themselves with) | The version from git tags at build time, `uv.lock` holding none (measured: uv writes the version as dynamic) | Adopted, as a build requirement only: nothing imports it at run time. The delta is configuration: `uv` rebuilding the install when the commit moves, and CI fetching the history the count is made from |
| A version written by hand in `pyproject.toml` | What `dossier` had | Rejected: it moves only when someone remembers, and `0.1.0` was 858 commits old when analysis_v2 counted |
| `git describe` asked at run time | A version that follows the source with no reinstall | Rejected: a subprocess on every command, and nothing to ask in an install with no checkout |

## Must hold

### R20.1 — a command that writes the workspace holds its lock, and a second one is refused at once, naming the first

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.lock.held_line`), infrastructure (`dossier.infrastructure.lock.WorkspaceLock`), cli
- **Proved by:** `tests/integration/test_R020_1__a_second_writer_is_refused.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` holding the workspace, pid 4120, since `2026-10-02T07:30:12Z`; `dossier sync incident-audit` started beside it | exit 2, before anything is read: `another dossier command is writing this workspace: run, pid 4120, since 2026-10-02T07:30:12Z. Try again when it has finished`; nothing synced |
| 2 | the same, `dossier gc --apply` | refused the same way; nothing deleted |
| 3 | *counter-example* — the same, `dossier status`, `dossier run incident-audit --plan` or `dossier gc` without `--apply` | each runs as before: none of them writes the workspace |
| 4 | *counter-example* — the run killed, its process gone | the next writer takes the lock: the system released it with the process |
| 5 | *counter-example* — `dossier sync incident-audit`, then `dossier run incident-audit`, one after the other | both run: a command lets the lock go when it ends |
| 6 | the lock held and `.dossier/lock.json` missing, or not the details a writer leaves | refused the same way, exit 2, without them: `another dossier command is writing this workspace. Try again when it has finished` |

### R20.2 — `dossier`'s version is derived from git when it is installed, and never written by hand

The value every manifest and record carries as `dossier_version` (R4.9,
R11.19). Rows 1 to 4 were measured on 2026-10-02 from a clone of this
repository at 884 commits, and `+g` is followed by the commit's abbreviated
hash.

- **Kind:** deterministic
- **Layer:** build (`pyproject.toml`, `.github/workflows/ci.yml`)
- **Proved by:** `tests/integration/test_R020_2__the_version_comes_from_git.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | installed from the commit tagged `v0.2.0` | `0.2.0` |
| 2 | installed three commits past `v0.2.0` | `0.2.1.dev3+g36a936027`: a development release of the next patch, three commits on, naming the commit |
| 3 | the same, with uncommitted changes | `0.2.1.dev3+g36a936027.d20261002`: the date says the source was not a commit |
| 4 | no tag yet, 884 commits | `0.1.dev884+g2e35b9c11` |
| 5 | *counter-example* — a source with no git history | the build refuses, naming `SETUPTOOLS_SCM_PRETEND_VERSION`; no version is made up |
| 6 | *counter-example* — a commit made after the install, with no `uv sync` | the version names the commit installed; the next `uv sync` rebuilds the install, because the commit is one of its cache keys |
| 7 | *counter-example* — `pyproject.toml` and `uv.lock` | neither names a version: `pyproject.toml` declares it dynamic, and the lock writes none for `dossier` |
