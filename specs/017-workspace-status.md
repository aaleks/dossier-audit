# 017 — Workspace status

**Status:** Implemented
**Rules:** R17.1 – R17.7

## Purpose

`dossier` keeps its state in four places: the ledger, `runs/`, `tries/` and the
gold sets. None of them says, in one place, what state the workspace is in. A
source that has not synced for a month, a document a sync still owes, and the
last run's failures are each found by opening a file. A judged field whose
calibration went stale is found only when `dossier eval` withholds it (R7.15),
after the run it scores has been paid for. `dossier status` says all of it
before anything is spent, and changes nothing while it does.

## What it prints

```
sources
  incidents-jira · 3 held · 0 tombstoned · last synced 2026-08-06T09:00:00Z
  procedures-confluence · 3 held · 0 tombstoned · last synced 2026-08-06T09:00:00Z
    owed 81920114.pdf, since 2026-08-06T09:00:00Z: <the error its sync recorded>
  incidents-manual · never synced
pipelines
  incident-audit · latest run 20260925T091500Z-5e6f · 4 documents · 1 failed
  postmortem-review · no run yet
judged fields · incident-audit against gold/incidents
  root_cause · withheld: calibration is stale: the judge prompt has changed since (R7.19)
```

- **`sources`** is every source `sources.yaml` declares, in its order, then any
  source the ledger still holds that it no longer declares. The counts are the
  ledger's rows. `last synced` is the source's watermark (R2.4), which moves
  only when a sync handled every item (R2.8). An owed document is one whose
  fetch failed and that the next sync will ask for again (R2.23).
- **`pipelines`** is every pipeline under `pipelines/`, by name. Its latest run
  is the last by run id, as `dossier eval` and `dossier gc` find it (R16.2). A
  document counts as failed once, however many of its steps failed it.
- **`judged fields`** is printed only for `dossier status PIPELINE --gold DIR`.
  A gold set can serve several pipelines (R3.7), and the rubrics a calibration is
  checked against are the pipeline's, so the question needs both, as `eval`
  does. The reason is the one `dossier eval PIPELINE --gold DIR` would print,
  word for word: one decision, `withholding` (R7.15, R7.23, R7.31), gives both.

A pipeline argument narrows `pipelines` to that one pipeline. The sources are
always printed whole.

`status` exits 0 whatever it finds. It informs, and the gates are `eval` and
`calibrate`. It exits 2 only when it cannot answer the question: a pipeline that
does not exist, `--gold` with no pipeline, `--gold` with a pipeline `eval` would
refuse to score because not exactly one of its steps declares an output, or a
file it has to read that does not load. It records nothing to MLflow, as
`--plan` and `gc`'s preview record nothing (R11.32). Decided by `a.aleks` on
2026-09-30.

Two things are left out on purpose:

- **Tries.** `gc` deletes every one, and a try answers a question about a
  subset (R4.20).
- **A failed listing.** Sync raises before it moves the watermark, and nothing
  in the ledger records that the listing failed. What a failed fetch leaves,
  the owed document, is printed. Recording a failed listing would change
  `sync`, and would be a spec 002 rule.

## Existing options considered

None. `status` reads `dossier`'s own ledger, manifests and calibrations, which
no general tool knows.

## Must hold

### R17.1 — `dossier status` names every source, with the documents it holds active and tombstoned and when it last synced

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.status.source_lines`), read by infrastructure (`dossier.infrastructure.ledger.read_held`, read-only)
- **Proved by:** `tests/unit/test_R017_1__status_names_every_source_and_what_it_holds.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira` holding `INC-4821`, `INC-4822` and `INC-4901`, watermark `2026-08-06T09:00:00Z` | `incidents-jira · 3 held · 0 tombstoned · last synced 2026-08-06T09:00:00Z` |
| 2 | `incidents-manual` holding `audit-note.pdf`, and `handover-note.md` tombstoned | `1 held · 1 tombstoned`: a tombstoned document is counted apart, not dropped |
| 3 | *counter-example* — `procedures-confluence` declared and never synced | `procedures-confluence · never synced`, with no counts: none is 0 held, which is a different state |
| 4 | *counter-example* — `incidents-jira` held in the ledger and no longer declared in `sources.yaml` | listed after the declared sources, with its counts and `· not in sources.yaml` |
| 5 | *counter-example* — `procedures-confluence`, whose first sync stored `OPS-115` and was refused `81920114.pdf`, so its watermark never moved (R2.8) | `procedures-confluence · 1 held · 0 tombstoned · no complete sync yet`: it holds a document, and there is no watermark to name |
| 6 | *counter-example* — no `sources.yaml`, and `incidents-jira` held in the ledger | `incidents-jira` with its counts and `· not in sources.yaml`, and exit 0: a workspace with no `sources.yaml` declares nothing, and what the ledger holds is still held |

### R17.2 — a source names each document a sync still owes it, with when its fetch failed and why

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.status.source_lines`), read by infrastructure (`dossier.infrastructure.ledger.read_held`, read-only)
- **Proved by:** `tests/unit/test_R017_2__status_names_what_a_sync_still_owes.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `81920114.pdf` refused `403` by `procedures-confluence`'s sync at `2026-08-06T09:00:00Z` (R2.23 row 1) | under the source: `owed 81920114.pdf, since 2026-08-06T09:00:00Z:` and the error the ledger recorded |
| 2 | two owed, `INC-4821/report.pdf` and `81920114.pdf` | one line each, by key |
| 3 | *counter-example* — nothing owed | no `owed` line |
| 4 | *counter-example* — a ledger written before R2.23, with no `owed` table | no `owed` line, and the ledger is read as it is: not migrated, its bytes unchanged |
| 5 | `procedures-confluence`, whose first sync was refused `OPS-114`, its only page | `procedures-confluence · 0 held · 0 tombstoned · no complete sync yet`, with `owed OPS-114` beneath: the ledger holds no row and no watermark for it, and `never synced` would hide what it is owed |

### R17.3 — `dossier status` names each pipeline's latest run, with its documents and how many of them a step failed

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.status.pipeline_lines`), read by application (`dossier.application.status`)
- **Proved by:** `tests/unit/test_R017_3__status_names_each_pipelines_latest_run.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incident-audit` with runs `20260806T142203Z-4f1a`, `20260907T090000Z-bbbb` and `20260925T091500Z-5e6f`, the last of four documents with `extract` failing `INC-4822` | `incident-audit · latest run 20260925T091500Z-5e6f · 4 documents · 1 failed` |
| 2 | `handover-note.md` failed by both `notes` and `extract` in the latest run (R6.29) | `1 failed`: a document is counted once, as R7.53 row 2 names it once |
| 3 | *counter-example* — `postmortem-review` under `pipelines/` with no run | `postmortem-review · no run yet` |
| 4 | *counter-example* — a directory under `runs/` with no `manifest.json`, named later than every run | not the latest run: it is not a run (R16.2 row 6) |
| 5 | *counter-example* — the latest run wrote no `failures.json`: it stopped before it ended (R4.27 row 5), or ran before R4.27 | `incident-audit · latest run 20260925T091500Z-5e6f · 4 documents · failures not recorded`: `0 failed` would say it finished and failed nothing, which `[]` alone says |

### R17.4 — `dossier status PIPELINE --gold DIR` names each judged field with the reason `dossier eval PIPELINE --gold DIR` would withhold it, or `reportable`

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.status.judged_fields`, asking `eval`'s own `dossier.cli.eval.judge_gate`), deciding by domain (`dossier.domain.judges.withholding`, `dossier.domain.status.judged_lines`)
- **Proved by:** `tests/unit/test_R017_4__status_names_what_eval_would_withhold.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause` calibrated at 0.97 against `gold/incidents/judge.yaml`'s 0.95, under the current judge model, rubric and prompt | `root_cause · reportable` |
| 2 | the judge prompt changed since that calibration | `root_cause · withheld: calibration is stale: the judge prompt has changed since (R7.19)`, the words `eval` prints for it |
| 3 | no `gold/incidents/calibrations/root_cause.json` | `root_cause · withheld: never measured`, and the instruction to run `dossier calibrate` that `eval` gives |
| 4 | a `per_part` step answering from pictures, `grounded` calibrated and clear, `described` never measured (R7.23 row 2) | `root_cause · withheld: described: never measured`: the state is named, as `eval` names it |
| 5 | *counter-example* — `dossier status incident-audit`, no `--gold` | no `judged fields` section, and nothing under `gold/` is read |
| 6 | *counter-example* — a pipeline whose output declares no judged field, with `--gold gold/incidents` | `judged fields · postmortem-review against gold/incidents` and `no judged fields` beneath it |

### R17.5 — `dossier status` changes no file

- **Kind:** deterministic
- **Layer:** application (`dossier.application.status`), infrastructure (`dossier.infrastructure.ledger`, opened read-only)
- **Proved by:** `tests/unit/test_R017_5__status_changes_no_file.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | R17.1 row 1's workspace, with a run and a calibration | after `dossier status incident-audit --gold gold/incidents`, every file in the workspace holds the bytes it held before, and none was added |
| 2 | *counter-example* — a workspace that has never synced, with no `.dossier/` | every source `never synced`, and no `.dossier/` is created: opening a ledger to read it would create one |

### R17.6 — `dossier status` exits 0 whatever it finds, and 2 only when it cannot answer

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.status`, refused in `eval`'s words by `dossier.cli.eval.scored_step`)
- **Proved by:** `tests/unit/test_R017_6__status_exits_zero_whatever_it_finds.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a document owed, a source never synced, and `root_cause` withheld | exit 0 |
| 2 | `dossier status incident-audit` | the `pipelines` section holds `incident-audit` alone; `sources` is printed whole |
| 3 | *counter-example* — `dossier status --gold gold/incidents`, no pipeline | exit 2, saying a gold set can serve several pipelines and naming the argument to give (R3.7); nothing on stdout |
| 4 | *counter-example* — `dossier status incident-audti` | exit 2, naming `incident-audti` as `dossier eval` names a pipeline it cannot find |
| 5 | *counter-example* — `dossier status incident-audit --gold gold/incidents`, with `extract` and `verify` both declaring an output | exit 2, with the refusal `dossier eval` gives, word for word: `incident-audit: 2 steps declare an output; eval scores exactly one`. Nothing on stdout: answering from the first would be the guess `eval` refuses to make |
| 6 | *counter-example* — `dossier status postmortem-review --gold gold/incidents`, no step declaring an output | exit 2, `postmortem-review: 0 steps declare an output; eval scores exactly one`, as `eval` refuses it |

### R17.7 — what `dossier status` says `dossier eval` will withhold is what it withholds

The outer loop. After a sync, a run and no calibration, `status` names the
field that eval then withholds, in the same words. After `dossier calibrate`,
`status` calls it `reportable`, and `eval` reports it.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.status`, `dossier.cli.eval`)
- **Proved by:** `tests/acceptance/test_R017_7__status_says_what_eval_will_withhold.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync`, `dossier run incident-audit`, then `dossier status incident-audit --gold gold/incidents` | `sources`, `pipelines` and `judged fields`, in that order; `root_cause · withheld: never measured`; exit 0 |
| 2 | then `dossier eval incident-audit --gold gold/incidents` | `root_cause` withheld with the reason `status` printed, word for word |
| 3 | *counter-example* — then `dossier calibrate`, and `status` again | `root_cause · reportable`, and the next `eval` reports `root_cause` with a percentage |
