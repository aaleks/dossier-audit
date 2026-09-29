# 004 — Step resolution and the run manifest

**Status:** Partially implemented
**Rules:** R4.1 – R4.25

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
- prompt file hashes, schema hashes, and the converters the run used with their versions (R8.9)
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

## Trying a prompt on one document

`dossier run <pipeline> --doc KEY` asks the pipeline about the named documents
only. It is how a prompt or a schema is iterated on: edit, try the document that
shows the problem, read what came back, and edit again. On 2026-09-29 the live
checks behind R6.25 ran exercise 10 four times, 9 calls each, when only
`PLAY-3005`'s 4 pages mattered. Aiming at one document took an in-memory patch
script, because the CLI could not.

A run over some documents is called a **try**. Its answers are real. They are
cached under the keys a full run uses, so the next full run is served them
(R4.21). A try is not a run, though. `dossier eval` scores the latest run,
`--plan` compares against it, and a new run warns when the source moved since
it. If a try counted as a run, a document of six would be scored as the
pipeline's result. So a try writes no manifest where those look (R4.20), and
its answers go somewhere of their own (R4.22).

Three choices were weighed, each decided by `a.aleks` on 2026-09-29.

**Where a try's answers go:**

| Option | For | Against |
|---|---|---|
| **`tries/<try_id>/`, named as `runs/` names them, and no manifest** (adopted) | nothing that reads `runs/` can mistake a try for a run, by construction | a try cannot be replayed or scored against gold; its answers are read by eye |
| A manifest in `runs/`, marked partial | a try replays, and an explicit `eval --run` could score its documents | every reader of `runs/` must honour the mark, and the one that does not is the defect this exists to prevent |
| The terminal only, no files | nothing to confuse | a page-by-page answer is hard to read and harder to compare between tries |

**What a step that reads every document does:**

| Option | For | Against |
|---|---|---|
| **Skipped, and the run says so** (adopted) | no call over a subset whose answer means nothing | an aggregate prompt cannot be tried on a small set |
| Asked over the named documents | an aggregate prompt tried cheaply | an answer about a subset, cached under a key no full run uses, easily read as the real report |
| `--doc` refused for such a pipeline | the simplest honest rule | most pipelines end in a report, so `--doc` would be unusable on them |

**What MLflow records of a try:**

| Option | For | Against |
|---|---|---|
| **Recorded as a run is, tagged a try, and not linked to the version it would have produced** (adopted) | every model call stays traced (spec 011), a try is one filter away, and a version's page lists only full runs (R13.2) | one tag more, and one exception to R13.2's link |
| Not recorded | MLflow holds full runs only | model calls that cost money and left no trace |
| Recorded as a run, with nothing to tell it apart | nothing to build | a try reads as a run, and links to the version as if it produced its results |

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

A reference document is part of what a run read, because every call reading
`reference` is shown it (R3.18). So row 4's warning names a moved procedure as
well as a moved incident, marked `(reference)` so a reader knows which kind of
evidence moved. Until row 5 it named only the audited documents, and a
tightened procedure went unmentioned until two runs were compared.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`) plus cli (the warning)
- **Proved by:** `tests/unit/test_R004_9__superseded_snapshots_do_not_affect_replay.py`, `tests/acceptance/test_R004_9__a_run_after_the_source_moved_warns.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a run pinned to `a3f9c1e2`, and `INC-4821` since re-snapshotted at a new hash | the replay reads `a3f9c1e2` |
| 2 | the same, with `INC-4821` since tombstoned | the replay still resolves (R2.7) |
| 3 | a *new* run of the same pipeline | pins the newer snapshot; only replay is frozen |
| 4 | *counter-example* — `dossier run` without `--replay`, after `INC-4821` was re-snapshotted | resolves against the current snapshot and prints `warning: the source has moved since run 20260806T142203Z-4f1a: INC-4821 re-snapshotted` before any step runs -- a document added or tombstoned since is named the same way |
| 5 | *counter-example* — `dossier run` without `--replay`, after reference document `OPS-114` was re-snapshotted | the same warning names it, marked as context: `warning: the source has moved since run 20260806T142203Z-4f1a: OPS-114 re-snapshotted (reference)`. A reference document that is new or deleted is named the same way |

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

A kind says how a step reads a document, not whether it does (R3.11). A step
reading `documents@page_images` reads the document as much as one reading
`documents`. Until rows 11 and 12, the plan asked whether a step read
`documents` by spelling alone, so a re-synced PDF printed `cached` for the step
reading its pages, and then that run asked the model about each page. A
converter moves only the steps that read its kind: `pdf-images` renders the
pages, and `pdf-markdown` renders none of them.

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
| 11 | `INC-4821` re-synced to new bytes; `describe` reads `documents@page_images` | `describe: documents changed` naming `INC-4821`; its pages are new bytes, and a run asks about each of them again |
| 12 | *counter-example* — `pdf-markdown` raised from `1.3.0` to `1.4.0`; `describe` reads only `documents@page_images` | `describe: cached`; `pdf-images` renders its pages and has not moved. `extract` and `verify` are `converters changed`, as in row 6 |
| 13 | `pdf-images` raised from `0.9.1` to `1.0.0` | `describe: converters changed`; `extract` and `verify`, which read no page, `cached` |

### R4.13 — a step naming a kind no source in its set produces stops the run at resolution

R3.11 lets a step name a kind. This is what happens when it names one nothing
will produce: the run stops before any model call, naming the step, the kind and
the sources that were asked for it.

Resolution's shape rather than conversion's (R8.24), because the two failures have
different fixes and different blast radii. R8.24 is "nothing converts this pair",
fixed by an installation. This is "your pipeline asked a source for something it
was never told to make", fixed by a line in `sources.yaml` — and it is knowable
from the configuration alone, before a single byte is fetched.

What a source declaring no `convert:` produces is *not* knowable here. R8.10
decides it per document from that document's media type, and which documents a
source holds is a fact about the source rather than about the configuration. So
an undeclared source is refused for naming nothing, never for producing
`markdown` — and a step reading bare `documents` against one is not refused at
all, because that is every pipeline written before a kind could be named
(R3.11).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.resolution.check_kinds`)
- **Proved by:** `tests/unit/test_R004_13__a_kind_must_be_one_its_sources_produce.py`, `tests/acceptance/test_R004_13__a_kind_no_source_produces_stops_the_run.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `describe` declaring `input: documents@page_images`, `incidents-manual` declaring no `convert:` | the run stops; the error names `describe`, `page_images` and `incidents-manual`, and says the source's `convert:` list is what grants it |
| 1a | that same error's wording | it says the source *declared nothing*, never that it "produces `['markdown']`" — which is false of an image source (R8.10 row 2), and sent the reader to look for a markdown converter for a PNG |
| 2 | the same, checked afterwards | zero model calls and no `runs/<id>/` directory; a resolution failure is total (R4.1) |
| 3 | `incidents-manual` declaring `convert: [markdown, page_images]` | resolves; both kinds are produced and the step reads one of them (R8.4) |
| 4 | two sources in `sources`, one declaring `convert: [markdown, page_images]` and one declaring none | stops, naming the source that cannot supply it; a step reads its whole set, and a half-answered input is the silent-gap failure this rule exists to prevent |
| 5 | *counter-example* — `extract` declaring `input: documents` against a source declaring `convert: [page_images]` | stops for the same reason, on the kind nobody wrote down: bare `documents` is `documents@markdown` (R3.11) and that source does not produce it |

### R4.14 — a replay reproduces a `per_part` step part by part

R3.12 gave a step a fan-out over the parts of its input and put each part in its
own key, and the replay was never taught about it. `_replay_one` recomposes a
stage key from the manifest with one input per declared target and no part in
it, so the key it builds is one no `per_part` run ever wrote. Every such run is
therefore irreproducible: `dossier run --replay` stops on the first document,
and `dossier eval` — which scores a replay, not the workspace — cannot score one
at all.

The parts are re-derived, not recorded. The manifest already pins each snapshot
and each converter it used, which is exactly what `replayed_inputs` recomposes
the text from; the container is fetched the same way and unpacked, so a replay
still reads nothing but entries the original run wrote (R4.7).

A part whose entry is gone stops the replay by name, naming the part and not
only the document — a document whose pages half resolved is not a document that
resolved, and R0.12 writes nothing at all rather than a run directory missing
two pages of six.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run.replay`)
- **Proved by:** `tests/unit/test_R004_14__a_replay_reproduces_a_per_part_step.py`, `tests/acceptance/test_R004_14__a_per_part_run_replays.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a replay of a run whose `describe` step read `INC-4830` as three page images | three artifacts reproduced, byte-identical to what the run wrote, and zero model calls |
| 2 | that replay written with `--replay` | `runs/<id>/replays/<rid>/describe/INC-4830.../page-001.md` through `page-003.md`, and nothing under the run's own directory touched (R0.12) |
| 3 | a described field in a reproduced `per_part` artifact | still `described`, not `ungrounded`: the replay knows which documents that stage was shown as pictures, so `dossier eval` scores what the run actually produced (R6.15) |
| 4 | one part's cache entry deleted | the replay stops naming the step, the document and the part, and writes no directory at all |
| 5 | *counter-example* — a `per_file` step | one key per document with no part in it, unchanged; nothing about a step that was never fanned out moves |

### R4.15 — a replay recomposes each group from the documents its manifest pins, never from what is held now

A group is its members, and a replay reproduces the call a run made, not the call
it would make today. The manifest already pins every document by key and snapshot
(R4.4), and a group is computed from keys alone (R3.15), so a replay recomposes the
groups a run asked about without their being recorded anywhere new. A document
synced since is invisible to the replay, as a changed prompt is (R4.7).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run.replay`)
- **Proved by:** `tests/unit/test_R004_15__a_replay_recomposes_groups_from_its_manifest.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a run pinning `ACME-2024/master.pdf`, `ACME-2024/amendment-1.pdf`, `ACME-2024/amendment-3.pdf` and `GLOBEX-2023/master.pdf`, replayed | `extract/ACME-2024.json` and `extract/GLOBEX-2023.json` reproduced byte for byte, and no model call |
| 2 | the same replay, after a sync fetched `ACME-2024/amendment-4.pdf` | still three members in `ACME-2024`, under the same key: membership comes from the manifest, not the ledger |
| 3 | *counter-example* — `dossier run` after that sync | four members, a new key and one model call (R5.14) |

### R4.16 — a manifest pins the reference documents apart from the audited ones, and a replay recomposes `{{reference}}` from them

A replay reproduces the calls a run made, and a call that read `reference` was
shown every reference document (R3.18). So the manifest has to say which of the
documents it pins were context and which were audited. Keys alone cannot say it,
as they can for a group (R4.15): `OPS-114` looks like a key from any source. The
manifest pins them under `reference`, by key and snapshot as it pins documents
(R4.4). A replay renders `{{reference}}` from that list and fans out over
`documents` alone. A procedure edited since the run is invisible to the replay,
as a prompt edited since is (R4.7).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.resolution.ResolvedPlan`), application (`dossier.application.run.replay`)
- **Proved by:** `tests/unit/test_R004_16__a_replay_recomposes_reference_from_its_manifest.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a run over `INC-4821` and `INC-4822` with reference `OPS-114` | the manifest pins `INC-4821` and `INC-4822` under `documents`, and `OPS-114` under `reference` |
| 2 | that run replayed | `verify/INC-4821.json` and `verify/INC-4822.json` reproduced byte for byte, with no model call |
| 3 | the same replay after `OPS-114` moved from `v37` to `v38` and was synced | still reproduced from `v37`, under the keys the run wrote |
| 4 | *counter-example* — a manifest written before this rule, with no `reference` list | read as no reference documents. A step of it that read `reference` cannot be reproduced, and the replay names its entry, as R3.13 row 5's runs cannot |

### R4.17 — `--plan` re-runs a step for a moved reference document exactly when the step reads `reference`

R4.12 promises that `--plan` reports a step as re-running exactly when a run would
miss its cache. A moved reference document moves the key of every call that
read it, and no other (R5.15). So a step that reads `reference` re-runs in full,
naming the reference document that moved, and a step that reads only
`documents` is still cached. Before this rule `--plan` treated every document
alike: a moved procedure would have reported `extract` as re-running, though
`extract` never read it.

A reference document that has gone is a move as well. An audited document that
leaves the source takes only its own keys with it, so a plan does not report it
(R4.12). A reference document was shown to every call that read `reference`, so
when one is tombstoned, every one of those keys moves (R5.15 row 3).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.plan.diff`), cli (`dossier.cli.run`)
- **Proved by:** `tests/unit/test_R004_17__a_moved_reference_document_reruns_the_steps_reading_it.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `OPS-114` moved, `verify` reading `[documents, extract, reference]` | `! verify: documents changed`, naming `OPS-114 changed` |
| 2 | the same, `extract` reading `documents` only | `extract: cached` |
| 3 | `OPS-116` tombstoned | `! verify: documents changed`, naming `OPS-116 gone`; `extract: cached` |
| 4 | *counter-example* — `INC-4821` moved | both steps re-run, each naming `INC-4821 changed` and no reference document |

### R4.18 — `dossier run --doc KEY` asks every step only about the named documents

A try is asked what a full run would ask about the named documents, and nothing
about any other ("Trying a prompt on one document", above). `--doc` may be given
more than once. A `per_group` step's unit is a group (R3.15), so it is asked about
each named document's whole group. A group missing some of its members would be a
different question (R4.15).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.plan`), application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R004_18__a_try_asks_only_about_the_named_documents.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract` `per_file` over `INC-4821`, `INC-4822`, `INC-4901`, `INC-5102` and `INC-5455`; `--doc INC-4821` | 1 model call, about `INC-4821` |
| 2 | `extract` `per_part` over `INC-4830` and `INC-5720`; `--doc INC-4830-postmortem-checkout-tls-expiry.pdf` | 3 model calls, one per page of `INC-4830`, and none for `INC-5720` |
| 3 | `--doc INC-4821 --doc INC-4822` | 2 model calls, one about each |
| 4 | a `per_group` step over `ACME-2024/`; `--doc ACME-2024/amendment-3.pdf` | 1 model call about group `ACME-2024`, holding every document of the group |
| 5 | *counter-example* — no `--doc` | every document, exactly as a run has always been asked |

### R4.19 — a `--doc` naming a document no source of the pipeline holds stops before any call, naming it

A key mistyped would otherwise be a try about nothing, printed as a success.
Every key is checked before anything is asked. A try that asked about the keys it
could find would look like the try that was meant.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.plan`), cli (`dossier.cli.run`)
- **Proved by:** `tests/unit/test_R004_19__a_document_no_source_holds_stops_a_try.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `--doc INC-4899` | exit 2, naming `INC-4899` as held by none of `incident-audit`'s sources; 0 model calls |
| 2 | `--doc INC-4821 --doc INC-4899` | the same, and `INC-4821` is not asked either |
| 3 | *counter-example* — `--doc INC-4821` | the try runs |

### R4.20 — a try writes no manifest under `runs/`, so the latest run is still the latest full run

`dossier eval` scores the latest run, `--plan` compares against it, and a run
warns when the source has moved since it (R4.9 row 4). Every one of them finds
that run by its manifest under `runs/`. A try writes none, so none of them can
mistake it for a run.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R004_20__a_try_is_never_the_latest_run.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a full run `20260806T142203Z-4f1a`, then `--doc INC-4821` | `runs/` holds `20260806T142203Z-4f1a` alone; `dossier eval incident-audit --gold gold/incidents` scores it |
| 2 | the same, then `dossier run incident-audit --plan` | compared against `20260806T142203Z-4f1a` |
| 3 | *counter-example* — a full run after the try | that run is the latest, as every run is |

### R4.21 — a try's answers are cached under the keys a full run would use, so the next full run is served them

What a try asks about is asked as a full run would ask it (spec 005). Nothing
about it being a try reaches a key, so its answers are never wasted.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R004_21__a_trys_answers_serve_the_next_full_run.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `--doc INC-4821`, then a full run over the five incidents | 4 model calls; `INC-4821` is served from cache |
| 2 | a full run, then `--doc INC-4821` | 0 model calls; the try is served its answer |
| 3 | *counter-example* — the prompt edited between the try and the full run | `INC-4821` asked again: the prompt is in the key (spec 005), whoever asked first |

### R4.22 — a try writes its answers under `tries/<try_id>/`, named as a run's are, and prints what a run prints

A try id has the form of a run id. Under it, each artifact is named as R0.11
names a run's, and as R0.13 names a `per_part` step's pages. The terminal shows
the step lines and every field finding as `dossier run` shows them (R6.16), so
reading a try is reading a run.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`), cli (`dossier.cli.run`)
- **Proved by:** `tests/unit/test_R004_22__a_try_writes_under_tries.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `--doc INC-4821` | `tries/20260929T100000Z-1a2b/extract/INC-4821.json` with its provenance record beside it; stdout opens `try 20260929T100000Z-1a2b · tries/20260929T100000Z-1a2b/`, then the step lines and findings |
| 2 | `--doc INC-4830-postmortem-checkout-tls-expiry.pdf`, `per_part` | `tries/<id>/extract/INC-4830-postmortem-checkout-tls-expiry.pdf/page-001.json` to `page-003.json` (R0.13) |
| 3 | *counter-example* — no `--doc` | `runs/<run_id>/` and its manifest, as every run (R0.11) |

### R4.23 — under `--doc`, a step that reads every document is skipped, and the try says so

An `aggregate` step's input is every document. Asked about the named ones, it
would answer a question about a subset, cached under a key no full run uses,
and easily read as the real report. So it is not asked, and the step line says
why. A step reading only a skipped step is not asked either, as a step is not
asked about what an earlier step did not produce (R6.13).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.plan`), cli (`dossier.cli.run`)
- **Proved by:** `tests/unit/test_R004_23__a_step_reading_every_document_is_skipped_in_a_try.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract` `per_file` then `report` `aggregate`; `--doc INC-4821` | 1 model call, `extract` about `INC-4821`; `report: skipped under --doc: it reads every document` |
| 2 | *counter-example* — the same pipeline, no `--doc` | `report` asked once over every document, as always |

### R4.24 — MLflow records a try as it records a run, tagged a try, and links it to no version as having produced it

Every model call a try makes is traced as a run's are (spec 011). The MLflow
run is tagged `dossier.try` with the named documents, sorted and joined by `, `,
so tries are one filter away. A try did not produce the pipeline version's
results, so it is not linked to the version as a record that produced them
(R13.2). A version's page lists only full runs.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R004_24__mlflow_records_a_try_as_a_try.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | tracking on, `--doc INC-4821 --doc INC-4822` | one MLflow run in `dossier-audit/incident-audit/run`, tagged `dossier.try` `INC-4821, INC-4822`; a trace per document and a span per model call, as a run's |
| 2 | the same | no link to the pipeline version as the record that produced it |
| 3 | *counter-example* — a full run, tracking on | no `dossier.try` tag, and linked to its version as it always was (R13.2) |

### R4.25 — a prompt is tried on one document, again and again, and the pipeline's result stays the last full run's

This is the slice's acceptance rule, observed through the CLI: the loop a person
iterates in, from a full run, through two tries with the prompt edited between
them, to the `eval` that still reports the full run. R4.18 to R4.24 can each be
MET while that loop is broken, so this rule is proved as a person runs it. The
documents are `INC-4830`, three pages read page by page, and `INC-5720`, one page
(`_fixtures.md`). The model is a `FakeModelClient` that counts calls.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.run`, `dossier.cli.eval`), application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R004_25__a_prompt_is_tried_on_one_document.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a full run (4 model calls), then `run --doc INC-4830-postmortem-checkout-tls-expiry.pdf` with the prompt edited | 3 more calls; the answers under `tries/<id>/`, and `runs/` holds the full run alone |
| 2 | the prompt edited again, and tried again | 3 more calls, under a second `tries/` directory |
| 3 | `dossier eval` after both tries | the full run's figures, `2 documents`; no model asked (R7.10) |
| 4 | *counter-example* — `run --doc INC-4899` | exit 2 naming `INC-4899`, and 0 calls |
