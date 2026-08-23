# 004 — Step resolution and the run manifest

**Status:** Proposed
**Rules:** R4.1 – R4.9

## Purpose

Relative references make configuration pleasant to write and dangerous to
execute. This spec removes the danger by expanding them once, before any work
starts, and freezing the result.

## Two phases

```
pipeline.yaml                          manifest.json
─────────────                          ─────────────
- id: extract                          extract  <- [documents]
  input: documents
- id: verify          ══ resolve ══>   verify   <- [documents, extract]
  input: previous
- id: report                           report   <- [verify]
  input: previous
```

After resolution the word `previous` does not exist anywhere in the system.
Execution reads only concrete ids.

## The manifest

Written to `runs/<run_id>/manifest.json` before the first stage executes:

- pipeline name and the hash of `pipeline.yaml`
- every step with its **expanded** input ids
- the exact snapshot content hashes pinned for this run
- prompt file hashes, schema hashes, converter versions
- the pinned model identifier
- `dossier` version and run start time

## Plan diffing

`dossier run <pipeline> --plan` resolves the pipeline, compares it against the
most recent manifest for that pipeline, and prints per step: `cached`,
`prompt changed`, `inputs changed`, `upstream changed`, or `new`. It executes
nothing.

Inserting a step between two others re-points the relative references below it.
That is a real change to the graph and appears in the diff:

```
! verify: inputs changed
      was: [documents, extract]
      now: [documents, enrich]
  -> cache invalid, will re-run (and report after it)
```

## Replay

`dossier run --replay runs/<run_id>/` executes from that run's frozen manifest
and ignores the current `pipeline.yaml` entirely.

## Must hold

### R4.1 — resolution completes fully before any stage executes

A resolution error means nothing ran, so a half-executed pipeline is never a
state the system can be in.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R004_1__resolution_completes_before_execution.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `report` referencing an unknown id, with `extract` and `verify` valid | no stage runs; zero model calls; the error names `report` |
| 2 | the same, checked against the run directory | no `runs/<id>/` directory is created |
| 3 | a pipeline that resolves cleanly | the manifest is written before the first stage is entered |
| 4 | *counter-example* — `verify` failing at execution time on `INC-4821` | `extract` has already run and is kept; execution failures are per-document (R6.9), resolution failures are total |

### R4.2 — `previous` expands to the preceding step id, `previous(n)` to the `n` preceding ids

In declaration order, so that reading the manifest never requires reading the
pipeline it came from.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.resolution.expand`)
- **Proved by:** `tests/unit/test_R004_2__previous_expands_in_declaration_order.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract`, `verify`, `report`; `report` declares `input: previous` | `report <- [verify]` |
| 2 | the same; `report` declares `input: previous(2)` | `report <- [extract, verify]`, in declaration order |
| 3 | `verify` declares `input: [documents, previous]` | `verify <- [documents, extract]`; mixing keywords and sugar is allowed |
| 4 | *counter-example* — `report` declares `input: verify` | already concrete; expansion leaves it untouched |

### R4.3 — `previous` with nothing preceding it is an error

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.resolution.expand`)
- **Proved by:** `tests/unit/test_R004_3__previous_without_a_predecessor_is_an_error.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract` is the first step and declares `input: previous` | error naming the step and that it has no predecessor |
| 2 | `verify` is second and declares `input: previous(2)` | error; `n` exceeds the one preceding step |
| 3 | `verify` is second and declares `input: previous(1)` | accepted; the bound is exact, not off by one |
| 4 | *counter-example* — `extract` declaring `input: documents` | accepted; a first step may read sources, it merely may not read a predecessor |

### R4.4 — the manifest contains only concrete ids

No relative reference survives resolution. This is what makes a manifest
readable years later without the configuration that produced it.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.resolution`)
- **Proved by:** `tests/unit/test_R004_4__manifest_holds_no_relative_references.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a pipeline using `previous` in two steps, resolved | the serialised manifest contains neither `previous` nor `previous(` anywhere |
| 2 | the resolved manifest for `incident-audit` | every input is `documents`, `reference`, or a declared step id |
| 3 | *counter-example* — the pipeline hash recorded in the manifest | covers the unresolved `pipeline.yaml` as written, including the word `previous`; the hash identifies the source, the inputs describe the run |

### R4.5 — reordering or inserting a step changes a resolved input list, and `--plan` shows it before anything runs

The trap this closes: an insertion looks local in the YAML and silently re-points
every relative reference below it.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.plan`)
- **Proved by:** `tests/acceptance/test_R004_5__inserted_step_shows_as_inputs_changed.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `enrich` inserted between `extract` and `verify`, `verify` using `previous` | `--plan` prints `verify: inputs changed`, `was: [documents, extract]`, `now: [documents, enrich]` |
| 2 | the same | `report` prints `upstream changed`, because `verify` will re-run |
| 3 | `extract` and `verify` swapped in declaration order | at least one resolved input list differs, and `--plan` reports it |
| 4 | *counter-example* — a comment added to `pipeline.yaml` | the pipeline hash changes; no resolved input list does, and every step still prints `cached` |

### R4.6 — `--plan` performs no model calls, writes no outputs and leaves the cache untouched

- **Kind:** deterministic
- **Layer:** application (`dossier.application.plan`)
- **Proved by:** `tests/acceptance/test_R004_6__plan_is_read_only.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit --plan` with the fake model client counting calls | zero calls |
| 2 | the cache directory before and after | byte-identical, including modification times of entries |
| 3 | a pipeline where every step would re-run | still zero calls and zero writes; `--plan` reports work, it does not do it |
| 4 | *counter-example* — reading the most recent manifest to diff against | a read, and permitted; the rule forbids writing and calling, not reading |

### R4.7 — `--replay` reproduces a past run byte-for-byte and touches no network

Regardless of what `pipeline.yaml` says today.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R004_7__replay_reproduces_a_past_run.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `runs/2026-08-06T14:22:03Z-4f1a/` replayed with the network stubbed to raise | completes; every artifact is byte-identical to the original |
| 2 | the same, with `pipeline.yaml` since edited to add a step | the edit is ignored; the manifest is the only input |
| 3 | the same, with the pinned model no longer named in `pipeline.yaml` | the manifest's model identifier is used (R0.6) |
| 4 | *counter-example* — a replay whose pinned snapshot is missing from the store | a clear error naming the missing hash; a replay may fail, but it may never silently substitute other content |

### R4.8 — resolving the same pipeline twice produces a byte-identical manifest

Apart from the run id and the start time, which are the only two fields that
record when rather than what.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.resolution`)
- **Proved by:** `tests/unit/test_R004_8__resolution_is_byte_identical.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `incident-audit` resolved twice in one process | identical bytes once run id and start time are excluded |
| 2 | resolved in two processes with different `PYTHONHASHSEED` | identical; no set ordering leaks into the output (R0.4) |
| 3 | resolved from two different working directories | identical; no absolute path is recorded |
| 4 | *counter-example* — a resolution after one fixture file changed | differs, in exactly one pinned snapshot hash; that difference is the point |

### R4.9 — a run whose pinned snapshots have been superseded still resolves and replays

Newer snapshots are ignored. A past audit is defended by what it actually read.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R004_9__superseded_snapshots_do_not_affect_replay.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a run pinned to `a3f9c1e2`, and `INC-4821` since re-snapshotted at a new hash | the replay reads `a3f9c1e2` |
| 2 | the same, with `INC-4821` since tombstoned | the replay still resolves (R2.7) |
| 3 | a *new* run of the same pipeline | pins the newer snapshot; only replay is frozen |
| 4 | *counter-example* — `dossier run` without `--replay`, after the source moved | resolves against current snapshots and warns that the source has moved since the last run |
