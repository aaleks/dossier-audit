# 004 — Step resolution and the run manifest

**Status:** Implemented
**Rules:** R4.1 – R4.12

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
`prompt changed`, `declaration changed`, `inputs changed`, `model changed`,
`converters changed`, `documents changed`, `upstream changed`, or `new`. It
executes nothing, and it is keyed exactly as a run is, so `cached` is a promise
the run keeps (R4.12).

A stage key covers the step's inputs, its prompt, its declaration, the pinned
model identifier and the hash of every input it reads (spec 005). The last three
are the ones a person does not think of as part of the pipeline at all — the
model is one line of YAML, the converters are installed packages, and the
documents are the corpus — and each of them moves a key:

```
! extract: documents changed
      moved: [PLAY-1001.md changed, PLAY-1005.md new]
  -> cache invalid for those documents, will re-ask for them
```

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
What it reproduces is written to a new directory under that run, or nowhere
(R0.12).

## Must hold

### R4.1 — resolution completes fully before any stage executes

A resolution error means nothing ran, so a half-executed pipeline is never a
state the system can be in.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R004_1__resolution_completes_before_execution.py`
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `runs/20260806T142203Z-4f1a/` replayed with the network stubbed to raise | completes; every artifact is byte-identical to the original |
| 2 | the same, with `pipeline.yaml` since edited to add a step | the edit is ignored; the manifest is the only input |
| 3 | the same, with the pinned model no longer named in `pipeline.yaml` | the manifest's model identifier is used (R0.6) |
| 4 | *counter-example* — a replay whose pinned snapshot is missing from the store | a clear error naming the missing hash; a replay may fail, but it may never silently substitute other content |

### R4.8 — resolving the same pipeline twice produces a byte-identical manifest

Apart from the run id and the start time, which are the only two fields that
record when rather than what.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.resolution`)
- **Proved by:** `tests/unit/test_R004_8__resolution_is_byte_identical.py`
- **Status:** MET

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
- **Proved by:** `tests/unit/test_R004_9__superseded_snapshots_do_not_affect_replay.py`, `tests/acceptance/test_R004_9__a_run_after_the_source_moved_warns.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a run pinned to `a3f9c1e2`, and `INC-4821` since re-snapshotted at a new hash | the replay reads `a3f9c1e2` |
| 2 | the same, with `INC-4821` since tombstoned | the replay still resolves (R2.7) |
| 3 | a *new* run of the same pipeline | pins the newer snapshot; only replay is frozen |
| 4 | *counter-example* — `dossier run` without `--replay`, after `INC-4821` was re-snapshotted | resolves against the current snapshot and prints `warning: the source has moved since run 20260806T142203Z-4f1a: INC-4821 re-snapshotted` before any step runs -- a document added or tombstoned since is named the same way |

### R4.10 — a document key two sources both hold stops the run, naming both

A run covers a set of documents, and a key identifies one of them. Two sources
holding the same key make that untrue, and nothing downstream can tell which
document a finding was about: `source.document` names a key (R6.3), a gold file
is keyed by one (spec 007), and a manifest pins one snapshot per key (R4.4).

Refused rather than qualified. Prefixing keys with their source would keep both
documents, and would also change what every gold file, every provenance record
and every report calls a document — a rename of the whole vocabulary to solve a
collision that has not happened yet. Refusing costs the user one rename and
cannot produce a wrong answer; the alternative that was there before, silently
keeping whichever source `sources:` listed last, produces an audit that covered
one document and reported the other.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R004_10__a_key_two_sources_hold_stops_the_run.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira` and `incidents-manual` both holding `INC-4821` | the run stops; the error names the key and both sources |
| 2 | the same, checked against the run directory | no `runs/<id>/` is created and no model call is made; a collision is a resolution failure (R4.1) |
| 3 | two sources holding `INC-4821` and `OPS-114` respectively | accepted; distinct keys across sources are the normal case and are not a collision |
| 4 | *counter-example* — the same source listed twice in `sources:` and `reference:` | not a collision; one source read twice is one document, and R2.12 already syncs it once |

### R4.11 — `previous(n)` for n greater than one resolves, and is refused before it runs

R4.2 expands `input: previous(2)` to the two preceding step ids, and a manifest
records them. What has no answer is how to *render* it: spec 003 injects each
declared input under its own labelled tag, and one placeholder cannot carry two
steps' outputs. The two halves of the contract cannot both be satisfied.

Refused during resolution, so a pipeline that cannot be rendered never writes a
manifest and never spends a model call (R4.1). It was previously discovered
inside the execution loop, which meant the steps above the offending one had
already run.

Naming the steps explicitly is the workaround and is also clearer:
`input: [extract, verify]` with `{{extract}}` and `{{verify}}` says what the
prompt receives. The sugar saves typing at the cost of a prompt nobody can write.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.resolution.validate_input_arity`)
- **Proved by:** `tests/unit/test_R004_1__resolution_completes_before_execution.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `report` declaring `input: previous(2)` after two steps | refused during resolution; the error names the step and both counts |
| 2 | the same, checked against the run directory | no `runs/<id>/` and no model call; a rendering that cannot exist is a resolution failure |
| 3 | `report` declaring `input: [extract, verify]` with both placeholders | accepted; naming them is the workaround and is clearer than the sugar |
| 4 | *counter-example* — `previous` and `previous(1)` | accepted; one declared input standing for one id renders exactly as R3.6 requires |

### R4.12 — `--plan` reports a step as re-running exactly when a run would miss its cache

A plan is a promise about a run: `cached` means the next run will serve that
step from the cache, and anything else means it will ask the model. The promise
holds only if the plan is keyed the way the run is. Until this rule `build_plan`
resolved without the prompt and declaration hashes `execute` keys on, so a
prompt edit printed `cached` and then missed -- one answer arrived at two ways.

The statuses are the ones spec 004's "Plan diffing" lists, plus `declaration
changed` for the file R6.11 hashes into a key: `new`, `inputs changed`, `prompt
changed`, `declaration changed`, `model changed`, `converters changed`,
`documents changed`, `upstream changed`, `cached`, checked in that order, so a
step whose prompt *and* inputs moved is reported for the change that re-points
the graph, and one whose model *and* documents moved is reported for the change
that affects every document rather than some.

Three of those statuses arrived after the rule did, and the reason is worth
recording: `diff` compared what a person edits in `pipelines/` and nothing else,
while a stage key also covers the pinned model identifier (R5.3), the converted
text of each document it reads (R5.4, R5.7), and therefore the snapshots behind
them. Changing `model:` printed `cached` and then asked the model for every
document; a re-synced note printed `cached` and then re-asked for that note. Both
are the failure this rule was written for, one level further out: the plan was
keyed the way a *pipeline* changes rather than the way a *run* does.

A departure is not a miss. A document that has left the source means strictly
less work -- every key that remains is the key it was -- so a shrinking corpus is
`cached`, and only an added or changed document re-asks.

Absence is not a change either. A manifest that pinned no converters has said
nothing about them, and reading that as "different converters" would print
`converters changed` on every plan against every older run. Not stated is its
own answer, as it is in a gold file (R7.3), and it is not "no".

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.plan.diff`)
- **Proved by:** `tests/unit/test_R004_12__a_plan_reruns_exactly_what_a_run_would_miss.py`, `tests/acceptance/test_R004_12__plan_says_prompt_changed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `prompts/02_verify.md` edited since the last run | `verify: prompt changed`; `report`, which reads it, `upstream changed`; `extract` `cached` -- exactly the steps a run would re-ask (R5.2) |
| 2 | `schemas/incident.yaml` edited | every step declaring it `declaration changed` (R6.11) |
| 3 | a comment added to `pipeline.yaml`, nothing else | every step `cached`; the pipeline hash moved and no key did (R4.5) |
| 4 | `model:` changed from `openai:gpt-5.4-mini` to another pinned identifier | every step `model changed`; the identifier is in every stage key (R5.3) |
| 5 | `INC-4821` re-synced to new bytes, nothing else touched | `extract`, which reads `documents`, `documents changed` naming `INC-4821`; `report`, which reads only `extract`, `upstream changed` |
| 6 | `pdf-markdown` raised from `1.3.0` to `1.4.0` | every step reading `documents` or `reference` `converters changed`; the converted text those steps read is addressed by the converter's version (R5.4) |
| 7 | *counter-example* — the retry wrapper dossier sends a validation error back in, edited | every step `cached`; in no key (R0.5 row 5), so in no plan |
| 8 | *counter-example* — `INC-4901` tombstoned since the last run, nothing else changed | every step `cached`; a departure is less work, and every remaining key is unmoved |
| 9 | *counter-example* — `DOSSIER_OPENAI_URL` pointed at another host | every step `cached`; where a model is served is in no key (R9.2) |
| 10 | *counter-example* — a manifest that pinned no converters at all | every step `cached`; absence is not a different converter, and reading it as one would report a change against every older run |
