# 013 — The pipeline version as an MLflow logged model

**Status:** Implemented
**Rules:** R13.1 – R13.5

## Purpose

A run records what it pinned, and an eval records what it scored, and both sit in
MLflow as rows in a list. What neither gives you is the thing a person actually
wants to compare: **this pipeline, at this version, is 80% accurate; the next
version is 90%**. MLflow has an object for exactly that -- a *logged model* --
and the column for it beside every `dossier` record has always been empty.

This spec says how a pipeline version is published as one, so that the Models
tab of a pipeline's experiment is one row per version with its accuracy on it,
and the question "did the prompt edit help" is a sort rather than an
archaeology.

## A word about the word "model"

In `dossier`, **model** means the LLM: `anthropic:claude-sonnet-4-5-20250929`,
pinned in `pipeline.yaml` and hashed into every key (spec 009). MLflow's
*logged model* is a different thing entirely -- the artefact being evaluated.
What `dossier` has that fits that slot is not the LLM but the **pipeline
version**: the prompts, schemas, converters and model pin a run used, identified
by a digest over all of them.

So the two names are kept apart everywhere. `dossier` says *pipeline version*;
MLflow stores it as a logged model; the LLM stays the *model*, and appears as a
**param** of the version rather than as the version itself. A spec that blurred
them would read as though `dossier` published the LLM, which it does not and
could not.

## The object

```
Models  ·  dossier-audit/incident-audit/run

  incident-audit  9c2b04f7   accuracy/overall 80.0   prompt/extract 77c1b40a
  incident-audit  4e8d13aa   accuracy/overall 90.0   prompt/extract 0e52dd18
```

One row per pipeline version. Its params are `version_params` (R11.18) -- the
pipeline hash, each step's prompt and schema hashes, the converters, the model
pin -- and one more: the **version hash**, a digest over all of them. Its metrics
are the accuracies the evals of that version measured. It is named after the
pipeline, because that is what a person is comparing versions *of*.

The version hash is the identity, and `pipeline_hash` is not. `pipeline_hash` is
`text_hash(pipeline.yaml)` and covers neither the prompts nor the schemas, so two
runs whose prompts differ share it -- and a version keyed on it would put an
edited prompt in the same row as the prompt it replaced. "Did the edit help" is
the question this tab is opened with, and it needs two rows to have an answer.
The corpus is deliberately *not* in the digest: a run over five documents instead
of four is the same version measured more widely, and folding the count in would
make every sync a new row with nothing to compare against.

It lives in the **run** experiment, rendered from `DOSSIER_MLFLOW_EXPERIMENT_RUN`
by R10.2, for the reason spec 012 puts a dataset in the eval experiment: a
version belongs beside the runs that produced it, not in a namespace of its own.
Evals reach across to it, as they already reach across to a dataset.

## Two ports, and why

Registering a version **returns** an id, which `Tracker`'s contract forbids and
R0.10 leans on. So `VersionRegistry` sits beside `Tracker` exactly as
`DatasetRegistry` does: the registry is allowed to read the server and hand
something back, and `Tracker` is told which version to link and never learns
anything.

```
VersionRegistry.register(...)  ->  PublishedVersion(version_id=...)
Tracker.produced_version(id)       this run made it        (a run's output)
Tracker.scored_version(id)         this run measured it    (an eval's input)
Tracker.log_version_metrics(...)   the figures it measured
```

The split matters here more than it did for datasets, because a version is
registered on `dossier run` -- the command whose whole promise is that tracking
cannot change what it produces (R10.4).

## Must hold

### R13.1 — a pipeline version is one ready logged model, found by its name and version hash or created

A pipeline version is identified by the pair **(pipeline name, version hash)**
and by nothing else. Creating one by name alone makes a new object every time, so
a registry that did not look first would leave one logged model per run and
compare nothing with nothing.

Neither half of the pair identifies on its own: two pipelines can resolve to one
digest, and one pipeline has many. Found means found by the conjunction.

The version hash and not `pipeline_hash`, for the reason above: the latter is the
hash of `pipeline.yaml` alone, and a prompt edit leaves it where it was.

A registered version is finalised ready. A model left pending is a record that
says something is still being written, which is untrue the moment the run that
produced it has ended.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.mlflow.MlflowVersionRegistry`)
- **Proved by:** `tests/unit/test_R013_1__a_version_is_identified_by_its_pipeline_and_hash.py`, `tests/acceptance/test_R013_1__a_run_registers_its_pipeline_version.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` at version `9c2b04f7`, nothing registered yet | one logged model named `incident-audit` in `dossier-audit/incident-audit/run`, `params.version_hash=9c2b04f7…`, `params.pipeline_hash=2f60a7d3…` and the rest of `version_params` beside it (R11.18), status ready |
| 2 | the same pipeline run again, unchanged | the same version id; 1 logged model, not 2. The second run found what the first registered |
| 3 | the same pipeline run again over a fifth document | still the same version. The corpus is not part of what a version *is*, so a sync does not open a row |
| 4 | the `verify` prompt edited, run again | a second version at `4e8d13aa`, beside the first in the Models tab, though `pipeline_hash` has not moved at all: two rows is the comparison the tab exists for, and keying on `pipeline_hash` would give one |
| 5 | *counter-example* — `postmortem-review` written byte-identically, so resolving to `9c2b04f7` | two versions, not one. The digest alone does not identify, and a registry matching on it would give one pipeline's accuracy to another |
| 6 | *counter-example* — a second `incident-audit` version at `4e8d13aa` while `9c2b04f7` exists | the name alone does not identify either. Only the pair does |
| 7 | *counter-example* — `dossier run --plan` or `--replay` | nothing registered. Neither produces a run, so neither produces a version (R11.1 row 5) |

### R13.2 — a record links to the version it produced or the version it scored, in the direction that says which

A run **made** a version; an eval **measured** one. MLflow holds those as
different edges -- an output and an input -- and they answer different questions:
"where did this version come from" and "what has been measured against it". One
edge in both directions would make an eval look like it produced the pipeline it
scored.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`, `dossier.application.eval`)
- **Proved by:** `tests/acceptance/test_R013_2__a_record_links_the_version_it_produced_or_scored.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` | the version on that run's **outputs**. Its page names what it built, which is the column this spec exists to fill |
| 2 | `dossier eval incident-audit --gold gold/incidents` over `20260806T142203Z-4f1a` | the version on the eval run's **inputs**. An eval consumes a version; it does not make one |
| 3 | an eval of a run made while tracking was off | the version is registered by the eval and linked as its input, with no run claiming to have produced it. What was scored is still recorded |
| 4 | `--compare 20260806T142203Z-4f1a 20260907T090000Z-bbbb` | both versions on the comparison's inputs. A comparison measures two, and naming one would be a claim about the pair that is false of half of it (R11.11 row 3) |
| 5 | *counter-example* — tracking off | no version, no link, and nothing under `runs/` or `.dossier/` differs by a byte (R10.4) |

### R13.3 — an eval's accuracy is recorded against the version it scored

The figures R11.3 already records on the eval's own run, recorded a second time
against the version -- which is the whole point, because a metric on a run
compares with other runs and a metric on a version compares with other versions.

Recorded, never computed: it is the same number, from the same totals, sent to a
second place. MLflow is a second place to read a figure and never a second way of
arriving at one (spec 011).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/acceptance/test_R013_3__an_eval_measures_the_version_it_scored.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the scoring example (R7.2) | `accuracy/overall` 80.0 and each `accuracy/<field>` on the version, the same values the eval's own run carries (R11.3) |
| 2 | the same run scored a second time | both figures on the one version, each naming the eval run it came from. A version accumulates its measurements; it does not replace them |
| 3 | `root_cause` withheld because its calibration is stale (R7.15) | no `accuracy/root_cause` on the version either. Nothing is measured for a number nobody may print (R7.17), and a version that carried one the report refused would be the disagreement spec 011 forbids |
| 4 | *counter-example* — `dossier calibrate` | `judge/root_cause/agreement` stays on the calibration run. It measures a judge, not a pipeline version, and a version is not what a judge was calibrated against (R11.5) |
| 5 | *counter-example* — a comparison's `delta/<field>` | not a version metric. A delta is a figure about a pair and belongs to neither half of it (R11.8) |

### R13.4 — a version id reaches a tag, a link and the terminal, and nothing on disk

The same promise R12.4 makes for a dataset id, restated for a second id that
comes back from a server. A version id may be printed, may be the link `Tracker`
records, and may reach an MLflow tag. It may not reach a cache key, a manifest,
a score, a provenance record or any file under `runs/` or `.dossier/`.

Restated rather than assumed, because this id arrives during `dossier run` --
the command R10.4 is about -- rather than during a command whose only output is
a record.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R013_4__a_version_id_reaches_nothing_on_disk.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` with tracking on, then the same run with it off | byte-identical manifests, stage keys, provenance records and files under `runs/` (R10.4, R5.6) |
| 2 | the version id `m-4746b054b65f4891b78c065e65a472ff` | printed on the run's MLflow line and nowhere else on disk |
| 3 | *counter-example* — a workspace whose registry returned a different id on a second run | the same cache keys, so every artifact is served from cache. A key that moved with a server-assigned id would make tracking an input to a run |

### R13.5 — a registry that cannot be reached does not fail the command

`dossier run` fetches nothing, converts nothing and asks no model differently
because MLflow is down. R10.6 already promises this of the tracker; a second port
on the same code path is a second way to break the promise, and it defaults to
the same answer: the work completes, the gap is reported, nothing is retried into
the run's own error path.

A gap is said out loud rather than swallowed silently, as R10.6 says a lost
trace is: a Models tab with nothing in it should not read as a pipeline nobody
ever ran.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.best_effort`)
- **Proved by:** `tests/unit/test_R013_5__a_registry_that_fails_does_not_fail_the_command.py`, `tests/acceptance/test_R013_5__a_run_survives_a_registry_that_is_down.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a registry raising on `register`, during `dossier run` | the run completes, exit 0, manifest written, every artifact under `runs/` present |
| 2 | the same | the command says the version could not be recorded, as it says a trace was lost (R10.6) |
| 3 | a registry that returns, and a `Tracker` that then fails to link | the same: the run completes and says so |
| 4 | *counter-example* — `dossier run` with tracking off entirely | no message. Nothing was attempted, so nothing was lost (R10.1) |
| 5 | *counter-example* — a model this machine cannot reach (R9.2 row 3) | still stops the run. A registry is not on the path that produces answers, and an endpoint is |
