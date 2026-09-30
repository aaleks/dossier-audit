# 016 — Reclaiming space

**Status:** Proposed
**Rules:** R16.1 – R16.7

## Purpose

Nothing in `dossier` deletes anything. Every run, try, replay, cached answer and
conversion stays on disk, and a PDF corpus with page images and a few weeks of
prompt iteration grows without limit. `dossier gc` reclaims that space. It
deletes old runs, and the cache entries only they needed, without ever making a
run it keeps impossible to reproduce. Deleting the cache is safe for the next
run (R5.9), which asks the model again. It is not safe for the runs already
made: a replay and an eval reproduce a run from its manifest and the cache
(R4.7, R7.10), and a run whose entries are gone cannot be scored again.

## What is kept, and what is not

| Held | `gc --apply` |
|---|---|
| `runs/<id>/` of the latest N runs of each pipeline, and of every run holding a `keep` file | kept: the manifest, `failures.json`, `keep`, and the artifact copies a person reads (R0.11) |
| `runs/<id>/` of every other run | deleted, whole |
| `runs/<id>/replays/`, under any run | deleted: byte copies of entries the run reproduces again at any time (R0.12) |
| `tries/<id>/` | deleted: a try is never replayed or scored (R4.20) |
| `.dossier/cache/stage`, `.dossier/cache/convert` | an entry is kept if a kept run's replay reads it; a conversion also if its snapshot is held now |
| `.dossier/cache/judge` | never touched: no manifest names a verdict, and a judge asked again can move a kept run's score (R7.18) |
| `.dossier/snapshots/`, `.dossier/ledger.db`, `gold/`, `pipelines/` | never touched (R0.2) |
| a directory under `runs/` with no `manifest.json` | never touched: it is not a run, and `runs/` is edited by people (R0.11) |

N is 5, and `--keep-last N` sets it for one invocation. A run's `--label` cannot
keep it. The label lives only in MLflow (R10.11), and `gc` reads nothing back
from there (R0.10). So a run is pinned on disk: `dossier gc --keep RUN` writes
`runs/<RUN>/keep`, and a person deletes that file to unpin it. Decided by
`a.aleks` on 2026-09-30, with 5, and with tries and replays always deleted.

What a kept run needs is found by tracing its replay: the keys that replay
reads, in the stage and convert caches, and nothing else. It is the replay the
kept run would get, so a key it reads cannot be missed by a second computation
of the keys that drifted from the first. The copies under `runs/` are never
read back (R0.11), so they decide nothing.

`dossier gc` with no `--apply` changes nothing. It prints what `--apply` would
delete and how much space that frees: the first command that deletes cannot do
so by accident (decided by `a.aleks` on 2026-09-30). Space is the bytes of every
file deleted, printed in MB of 10^6 bytes to one decimal.

`gc` takes no lock. Run beside a `dossier run`, it can delete entries that run
is writing and no manifest names yet. A lock between commands is its own
feature, and until one exists, `gc` is run when nothing else is.

## Existing options considered

None. What is safe to delete depends on how `dossier`'s own manifests, caches
and records refer to one another, which no general tool knows.

## Must hold

### R16.1 — after `dossier gc --apply`, every kept run that replayed before replays as it did, and scores as it did

The slice's acceptance rule, proved through the CLI. The rules below each
decide part of what goes. Any one of them can be right while a kept run no
longer reproduces, and that is the one thing `gc` must never do.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.gc`), application (`dossier.application.gc`)
- **Proved by:** `tests/acceptance/test_R016_1__a_kept_run_replays_after_gc.py`
- **Status:** IN PROGRESS

| # | Given | Then |
|---|-------|------|
| 1 | `incident-audit` run as `20260806T142203Z-4f1a`, `20260907T090000Z-bbbb` and `20260925T091500Z-5e6f`, the prompt edited before each of the last two, then a try of `INC-4821`; `dossier gc --keep-last 2 --apply` | `runs/20260806T142203Z-4f1a/`, the entries only it read, and the try deleted; `--replay` of `20260907T090000Z-bbbb` and of `20260925T091500Z-5e6f` each reproduces every artifact, with 0 model calls |
| 2 | the same | `dossier eval incident-audit --gold gold/incidents` prints what it printed before `gc`, line for line, and asks no model |
| 3 | the same | `dossier eval incident-audit --gold gold/incidents --compare 20260907T090000Z-bbbb 20260925T091500Z-5e6f` prints what it printed before `gc`: the change gate still works across the runs kept |
| 4 | *counter-example* — `dossier gc --keep-last 2 --apply` again at once | `nothing to collect`; no file under `runs/`, `tries/` or `.dossier/` changes |

### R16.2 — `gc` keeps the latest N runs of each pipeline and every run holding a `keep` file, and deletes every other run

A run is a directory under `runs/` holding `manifest.json`, and its pipeline is
the one its manifest names. The latest are the last by run id, which sorts by
the time the run started (R0.8), as `dossier eval` finds the latest run.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.gc.kept_runs`)
- **Proved by:** `tests/unit/test_R016_2__the_latest_runs_of_each_pipeline_are_kept.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `incident-audit` with seven runs, none pinned | the five latest kept, the two oldest deleted |
| 2 | the same seven, `--keep-last 1` | the latest kept, six deleted: the number is read, not fixed at five |
| 3 | the same seven, the oldest, `20260806T142203Z-4f1a`, holding `keep` | it is kept beside the five latest, and one run is deleted |
| 4 | `incident-audit` with six runs, and `postmortem-review` with two | `incident-audit`'s oldest deleted, and both of `postmortem-review`'s kept: each pipeline keeps its own five |
| 5 | *counter-example* — `incident-audit` with three runs | all three kept, none deleted |
| 6 | *counter-example* — a directory under `runs/` with no `manifest.json` | neither kept nor deleted: it is not a run, and `gc` leaves what it cannot account for |

### R16.3 — `gc` deletes a stage or convert entry only when no kept run's replay reads it and, for a conversion, its snapshot is not held now

A kept run is reproduced from its manifest and the cache, its answers and
conversions read by key (R4.7). So the entries its replay reads must survive,
whichever run first wrote them: two runs that asked the same question share one
entry, and a try's answer is the entry a later run is served (R4.21). A
conversion of a snapshot the ledger holds now is kept whether or not a run read
it: the next run reads it, and re-converting a scanned PDF takes minutes
(spec 008). An entry's provenance record goes with it.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.gc.collectable`), application (`dossier.application.gc`)
- **Proved by:** `tests/unit/test_R016_3__an_entry_a_kept_run_reads_is_never_deleted.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract`'s entry for `INC-4821`, read only by `20260806T142203Z-4f1a`, which is deleted | deleted, with its provenance record |
| 2 | `extract`'s entry for `INC-4822`, whose inputs did not change between `20260806T142203Z-4f1a` and the kept `20260907T090000Z-bbbb` | kept: it is one entry, and a kept run reads it |
| 3 | the answer a try of `INC-4830` cached, which the kept `20260925T091500Z-5e6f` was then served (R4.21) | kept |
| 4 | a conversion of `INC-4821`'s current snapshot, made by `dossier convert` after the latest run | kept: the document is held now, and the next run reads it |
| 5 | *counter-example* — the conversion of `INC-4821`'s previous snapshot, which no kept run read | deleted |
| 6 | *counter-example* — `.dossier/cache/judge`, `.dossier/snapshots/` and `.dossier/ledger.db` | not a byte changes |

### R16.4 — `gc` deletes every try and every replay, under a kept run as well

A try is never replayed or scored (R4.20), and an answer of its that a run was
served is that run's entry (R16.3 row 3). A replay is byte copies of entries its
run reproduces again at any time (R0.12). What else a kept run holds stays.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.gc`)
- **Proved by:** `tests/unit/test_R016_4__tries_and_replays_are_deleted.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `tries/20260929T100000Z-1a2b/` | deleted |
| 2 | `runs/20260806T142203Z-4f1a/replays/20260918T140000Z-1e2f/`, under `20260806T142203Z-4f1a` pinned with `keep` | deleted; the run is kept |
| 3 | *counter-example* — that kept run's `manifest.json`, `failures.json`, `keep` and `extract/INC-4821.json` | kept |

### R16.5 — `dossier gc` without `--apply` deletes nothing, and prints what `--apply` would delete and the space it would free

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.gc`), domain (`dossier.domain.gc`)
- **Proved by:** `tests/unit/test_R016_5__gc_previews_unless_told_to_apply.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | R16.1 row 1's workspace; `dossier gc --keep-last 2` | `would free … MB: 1 run, 1 try, 0 replays, … cache entries`, then `  runs/20260806T142203Z-4f1a/  incident-audit, beyond the latest 2`, then ``nothing deleted: run `dossier gc --apply` to delete it``; no file changes; exit 0 |
| 2 | the same, `--apply` | `freed … MB: 1 run, 1 try, 0 replays, … cache entries`, the counts and the size the preview printed, and the same line for the run |
| 3 | *counter-example* — nothing to collect, with or without `--apply` | `nothing to collect`; exit 0 |

### R16.6 — `dossier gc --keep RUN` pins a run by writing `runs/<RUN>/keep`, and refuses a run that does not exist

Pinning deletes nothing, so it is done with or without `--apply`, before the
rest of the command.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.gc`)
- **Proved by:** `tests/unit/test_R016_6__keep_pins_a_run.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier gc --keep 20260806T142203Z-4f1a` | `runs/20260806T142203Z-4f1a/keep` written, and the preview counts that run as kept (R16.2 row 3) |
| 2 | a later `dossier gc --apply`, with no `--keep` | the run still kept: the pin is on disk, not in a command |
| 3 | *counter-example* — `dossier gc --keep 20260101T000000Z-0000`, which no run has | exit 2, `no run 20260101T000000Z-0000 -- expected runs/20260101T000000Z-0000/manifest.json`; nothing written and nothing deleted |

### R16.7 — a kept run that already cannot be replayed is named, and does not stop `gc`

What `gc` guarantees is that a run which replayed before it replays after it
(R16.1). A kept run whose replay already stops, on an entry deleted by hand or
a run killed before it ended, could not be reproduced before `gc` either.
Stopping `gc` would protect nothing, and a run stopped with Ctrl-C, the latest
and so kept, would block every `gc` until it was deleted by hand. The entries
its replay read before it stopped are kept: what it did resolve.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.gc`)
- **Proved by:** `tests/unit/test_R016_7__an_unreplayable_kept_run_does_not_stop_gc.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `20260925T091500Z-5e6f`, the latest run, killed during `verify`, so that no entry holds `verify`'s answer for `INC-4822` | on stderr, `  kept as it is: runs/20260925T091500Z-5e6f/ cannot be replayed: ` and the replay's own error; `gc` goes on, and exits 0 |
| 2 | the same | the `extract` entries its replay read before it stopped are kept |
| 3 | *counter-example* — every kept run replays | no `kept as it is` line |
