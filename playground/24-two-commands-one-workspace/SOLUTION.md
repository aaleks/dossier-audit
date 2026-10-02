# 24 · Solution

Every command below was run against this repository, in order and in one pass,
on 2026-10-02, against the stub with `--delay 4`. The output shown is the output
it produced, from the README's commands, with the workspace's absolute path cut
from the `run` lines. The pids, times and run ids are that pass's, and yours
will differ. It ran on Windows, where `kill -9` is `taskkill /F`.

---

## Task 1 — a sync beside a run

Terminal 3, while the run in terminal 2 asks its first question:

```console
$ $D sync incident-review; echo $?
another dossier command is writing this workspace: run, pid 5500, since 2026-10-02T16:39:24Z. Try again when it has finished
2

$ cat .dossier/lock.json
{"command": "run", "pid": 5500, "since": "2026-10-02T16:39:24Z"}

$ $D status
sources
  incidents · 4 held · 0 tombstoned · last synced 2026-10-02T16:39:23Z
pipelines
  incident-review · latest run 20261002T163924Z-ebc5 · 4 documents · failures not recorded
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
incident-review  4 document(s) · model openai:gpt-5.4-mini
compared against 20261002T163924Z-ebc5
  extract: cached
  summary: cached
      model: openai:gpt-5.4
0 of 2 step(s) would run · nothing written
0

$ $D gc; echo $?
nothing to collect
  kept as it is: runs/20261002T163924Z-ebc5/ cannot be replayed: step 'extract' has no cached artifact for 'PLAY-1002.md' at 4b35046ad28f...; this run cannot be reproduced from this workspace, and nothing has been substituted for it.
0

$ $D gc --apply; echo $?
another dossier command is writing this workspace: run, pid 5500, since 2026-10-02T16:39:24Z. Try again when it has finished
2

$ $D convert incident-review; echo $?
another dossier command is writing this workspace: run, pid 5500, since 2026-10-02T16:39:24Z. Try again when it has finished
2
```

And terminal 2, twenty seconds later:

```console
run 20261002T163924Z-ebc5 · …\runs\20261002T163924Z-ebc5\manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · tokens not reported
  summary: 1 document(s) · 0 from cache · 0 failed · tokens not reported
```

The line falls between commands that write a ledger, snapshot, run, stage or
convert entry, index row or gold file, and commands that don't. `--plan` and
the `gc` preview write nothing, so they run beside the run. `gc --apply`
deletes and `convert` writes convert entries, so both are refused. That
conversion is cached and harmless to repeat does not move `convert` across:
the line is drawn by what a command writes.

The readers see the workspace as the run has left it so far. The plan compares
against the run still going, as though it had ended. `status` says `failures
not recorded`, because the run has written no failures file yet. The `gc`
preview keeps the run and says it cannot be replayed: `PLAY-1001.md` had been
answered and `PLAY-1002.md` not yet. Each is right about the moment it read.
None of them is wrong in a way that costs anything, because none of them
deletes or writes.

## Task 3 — killed halfway

After the prompt edit, with the new run started:

```console
$ kill -9 37088
(terminal 2: the run ends, exit 1)

$ ls .dossier/
cache  ledger.db  lock  lock.json  snapshots

$ cat .dossier/lock.json
{"command": "run", "pid": 37088, "since": "2026-10-02T16:39:45Z"}

$ $D status
sources
  incidents · 4 held · 0 tombstoned · last synced 2026-10-02T16:39:23Z
pipelines
  incident-review · latest run 20261002T163945Z-ac3f · 4 documents · failures not recorded

$ $D sync incident-review; echo $?
incidents  4 known · 0 changed · 0 new -> 4 fetched
ledger updated · 0 new snapshots · 0 tombstoned
0

$ cat .dossier/lock.json
{"command": "sync", "pid": 22264, "since": "2026-10-02T16:39:53Z"}
```

Before the new run wrote its details, `lock.json` still named the run from
task 2. The details follow the lock, so for a moment the file names whoever
held the workspace last. The script that first recorded this solution read the
file in that moment and killed a pid that had already ended. That is why the
task says to wait for a later `since`. When the file is missing or half written, a
refused command is refused all the same, without the details (R20.1 row 6).
The lock is what refuses, and the file only says who.

Both files outlive the kill, and that is fine. The lock is not the file: it is
the operating system's lock on the file (`fcntl.flock`, or `msvcrt.locking` on
Windows), and the system let it go when the process ended. `lock.json` naming
a dead run is read only when a command is refused, and no command was.

With an `O_EXCL` lock file, the kill would have left the file behind, and
every command after it would have been refused until a person deleted it. A
daily job would stop for good on the first run killed by a reboot.

`status` says `failures not recorded` rather than `0 failed`. A run killed
before it ended wrote no failures file, and "none recorded" is not "none"
(spec 017).

## Task 4 — one after another

```console
$ $D sync incident-review && $D run incident-review; echo $?
incidents  4 known · 0 changed · 0 new -> 4 fetched
ledger updated · 0 new snapshots · 0 tombstoned
run 20261002T163955Z-d523 · …\runs\20261002T163955Z-d523\manifest.json
  extract: 4 document(s) · 1 from cache · 0 failed · tokens not reported
  summary: 1 document(s) · 1 from cache · 0 failed
0
```

The sync let the lock go when it ended, and the run took it. One extract was
served from cache: the killed run had answered `PLAY-1001.md` before the kill,
and its answer was cached whole.

At 06:00 with yesterday's run still going, today's sync is refused, exits 2,
and the `&&` never starts today's run. Cron mails the one line, naming
yesterday's run, its pid and since when. The day after, if yesterday's run has
finished, both run as normal. Nothing has to be cleaned up in between.
