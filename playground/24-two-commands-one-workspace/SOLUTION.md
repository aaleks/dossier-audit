# 24 · Solution

Every command below was run against this repository, in order and in one pass,
on 2026-10-02, against the stub with `--delay 4`. The output shown is the output
it produced, from the README's commands, with the workspace's absolute path cut
from the `run` lines. A command's standard error is shown where a terminal shows
it, before what it prints after. The pids, times, run ids and commits are that
pass's, and yours will differ. It ran on Windows, where `kill -9` is
`taskkill /F`.

---

## Task 1 — a sync beside a run

Terminal 3, while the run in terminal 2 asks its first question:

```console
$ $D sync incident-review; echo $?
another dossier command is writing this workspace: run, pid 3396, since 2026-10-02T17:26:02Z. Try again when it has finished
2

$ cat .dossier/lock.json
{"command": "run", "pid": 3396, "since": "2026-10-02T17:26:02Z"}

$ $D status
sources
  incidents · 4 held · 0 tombstoned · last synced 2026-10-02T17:26:01Z
pipelines
  incident-review · latest run 20261002T172602Z-cd3e · 4 documents · failures not recorded
```

The sync was refused before it read anything: it built no connector and
fetched nothing. `last synced` is still the setup's sync, a second before the
run started. Exit 2 is what any mistake in the workspace gives, so a script
that runs `dossier` stops on it.

The pid and the time are the run's own, written to `lock.json` once it held
the lock. The pid is the process that holds the lock, the one `ps` shows
running `dossier run`. On Windows, a venv's `python.exe` is a launcher, and the
pid is the interpreter it started.

The refusal does not wait, because waiting fails worse. A daily job that waits
behind a run that outlasts its day starts tomorrow's sync late. Then
tomorrow's job waits behind it, and a hung run quietly stops every job after
it. Refused at once, the job fails plainly, cron mails the line, and the next
day's job runs as normal. Spec 020 records this as a decision, made against
waiting a while before refusing.

## Task 2 — the commands that only read

```console
$ $D run incident-review --plan; echo $?
  passed over: runs/20261002T172602Z-cd3e/ has no failures.json: it stopped before it ended, or has not ended yet
incident-review  4 document(s) · model openai:gpt-5.4-mini
no previous run to compare against
! extract: new
! summary: new
      model: openai:gpt-5.4
2 of 2 step(s) would run · nothing written
0

$ $D gc; echo $?
nothing to collect
  kept as it is: runs/20261002T172602Z-cd3e/ cannot be replayed: step 'extract' has no cached artifact for 'PLAY-1001.md' at f932eb18a3b2...; this run cannot be reproduced from this workspace, and nothing has been substituted for it.
0

$ $D gc --apply; echo $?
another dossier command is writing this workspace: run, pid 3396, since 2026-10-02T17:26:02Z. Try again when it has finished
2

$ $D convert incident-review; echo $?
another dossier command is writing this workspace: run, pid 3396, since 2026-10-02T17:26:02Z. Try again when it has finished
2
```

And terminal 2, twenty seconds later:

```console
run 20261002T172602Z-cd3e · …\runs\20261002T172602Z-cd3e\manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · tokens not reported
  summary: 1 document(s) · 0 from cache · 0 failed · tokens not reported
```

The line falls between commands that write a ledger, snapshot, run, stage or
convert entry, index row or gold file, and commands that don't. `--plan` and
the `gc` preview write nothing, so they run beside the run. `gc --apply`
deletes and `convert` writes convert entries, so both are refused. That
conversion is cached and harmless to repeat does not move `convert` across:
the line is drawn by what a command writes.

The readers see the workspace as the run has left it so far, and each says so
in its own way. `status` names the run as the latest, with `failures not
recorded`, because it has written no `failures.json` yet. The `gc` preview
keeps it and says it cannot be replayed, since `PLAY-1001.md` has no answer
yet. The plan passes over it. A run writes its manifest before it asks
anything, so a manifest is no promise that its answers are cached, and a
`cached` against it would be a promise the next run might not keep (R4.31).
With no finished run before it, every step is `new`. None of the three is
wrong in a way that costs anything, because none of them deletes or writes.

## Task 3 — killed halfway

After the prompt edit, with the new run started:

```console
$ kill -9 12032
(terminal 2: the run ends, exit 1)

$ ls .dossier/
cache  ledger.db  lock  lock.json  snapshots

$ cat .dossier/lock.json
{"command": "run", "pid": 12032, "since": "2026-10-02T17:26:23Z"}

$ $D status
sources
  incidents · 4 held · 0 tombstoned · last synced 2026-10-02T17:26:01Z
pipelines
  incident-review · latest run 20261002T172623Z-a1bc · 4 documents · failures not recorded

$ $D run incident-review --plan
  passed over: runs/20261002T172623Z-a1bc/ has no failures.json: it stopped before it ended, or has not ended yet
incident-review  4 document(s) · model openai:gpt-5.4-mini
compared against 20261002T172602Z-cd3e
! extract: prompt changed
! summary: upstream changed
      model: openai:gpt-5.4
2 of 2 step(s) would run · nothing written

$ $D sync incident-review; echo $?
incidents  4 known · 0 changed · 0 new -> 4 fetched
ledger updated · 0 new snapshots · 0 tombstoned
0

$ cat .dossier/lock.json
{"command": "sync", "pid": 24864, "since": "2026-10-02T17:26:31Z"}
```

Before the new run wrote its details, `lock.json` still named the run from
task 2. The details follow the lock, so for a moment the file names whoever
held the workspace last. The script that first recorded this solution read the
file in that moment and killed a pid that had already ended. That is why the
task says to wait for a later `since`. When the file is missing or half
written, a refused command is refused all the same, without the details
(R20.1 row 6). The lock is what refuses, and the file only says who.

Both files outlive the kill, and that is fine. The lock is not the file: it is
the operating system's lock on the file (`fcntl.flock`, or `msvcrt.locking` on
Windows), and the system let it go when the process ended. `lock.json` naming
a dead run is read only when a command is refused, and no command was.

With an `O_EXCL` lock file, the kill would have left the file behind, and
every command after it would have been refused until a person deleted it. A
daily job would stop for good on the first run killed by a reboot.

`status` says `failures not recorded` rather than `0 failed`. A run killed
before it ended wrote no failures file, and "none recorded" is not "none"
(spec 017). The plan passes over the killed run for the same reason, and
compares against task 2's, which finished. Against that one, the prompt has
changed, so `extract` will be asked again. Until R4.31 the plan compared
against the killed run, printed `extract: cached` and `0 of 2 step(s) would
run`, and the next run then asked three of the four notes. This exercise is
where that was found.

## Task 4 — one after another

```console
$ $D sync incident-review && $D run incident-review; echo $?
incidents  4 known · 0 changed · 0 new -> 4 fetched
ledger updated · 0 new snapshots · 0 tombstoned
run 20261002T172632Z-28e2 · …\runs\20261002T172632Z-28e2\manifest.json
  extract: 4 document(s) · 1 from cache · 0 failed · tokens not reported
  summary: 1 document(s) · 1 from cache · 0 failed
0
```

The sync let the lock go when it ended, and the run took it. One extract was
served from cache: the killed run had answered `PLAY-1001.md` before the kill,
and its answer was cached whole. The plan said `extract` would run, and it
did, for the three notes the killed run never answered.

At 06:00 with yesterday's run still going, today's sync is refused, exits 2,
and the `&&` never starts today's run. Cron mails the one line, naming
yesterday's run, its pid and since when. The day after, if yesterday's run has
finished, both run as normal. Nothing has to be cleaned up in between.

## Task 5 — which `dossier` wrote it

The checkout had moved three commits since `dossier` was last installed. This
is what the three runs above recorded, then what one more run recorded after a
`uv sync`:

```console
$ grep -h '"dossier_version"' runs/*/manifest.json
  "dossier_version": "0.1.dev884+gda1feaae7.d20261002",
  "dossier_version": "0.1.dev884+gda1feaae7.d20261002",
  "dossier_version": "0.1.dev884+gda1feaae7.d20261002",

$ git -C ../../.. log --oneline -1
0c76133 R4.31: the passed-over line says what the plan sees, for a run killed or still going

$ uv sync && $D run incident-review
run 20261002T173600Z-f5d7 · …\runs\20261002T173600Z-f5d7\manifest.json
  extract: 4 document(s) · 4 from cache · 0 failed
  summary: 1 document(s) · 1 from cache · 0 failed

$ grep -h '"dossier_version"' runs/*/manifest.json
  "dossier_version": "0.1.dev884+gda1feaae7.d20261002",
  "dossier_version": "0.1.dev884+gda1feaae7.d20261002",
  "dossier_version": "0.1.dev884+gda1feaae7.d20261002",
  "dossier_version": "0.1.dev887+g0c7613321.d20261002",
```

`0.1.dev887` is a development release of 0.1, 887 commits from the start of
the history, because no commit is tagged yet. `+g0c7613321` is the commit,
the one `git log` names. `.d20261002` says the checkout had uncommitted
changes on 2026-10-02 when it was installed, so the commit alone does not say
what ran.

The first three runs name `da1feaae7`, three commits behind the checkout. An
editable install runs the source as it is, but its version was fixed when it
was built, at the last `uv sync`. The sync rebuilt it because the commit had
moved: the commit is one of the install's cache keys (R20.2 row 6). The
version is fixed at install because that is when the build reads git. A
version asked of git at run time would cost a subprocess on every command, and
would have nothing to ask in an install with no checkout (spec 020, "Existing
options considered").

The commit tagged `v0.2.0` installs as `0.2.0`. Three commits after it, it
installs as `0.2.1.dev3+g` and that commit: a development release on the way
to the next patch. Those two were measured by building from a tagged clone
(R20.2 rows 1 and 2).
