# 011 — What each command records to MLflow

**Status:** Partially implemented
**Rules:** R11.1 – R11.7

## Purpose

Spec 010 says whether tracking is on and where its records go. This spec says
what lands there, per command, so that the record of a run answers the questions
people actually open MLflow with: which document was slow, which one was retried
and why, which field regressed, and against which gold set.

Every figure recorded here is one `dossier` already computes and prints. MLflow
is a second place to read it, never a second way of computing it -- a metric
that could disagree with the terminal would leave nobody sure which to believe.

## What is recorded

| Command | MLflow run | Traces | Metrics |
|---|---|---|---|
| `dossier run` | one, named after the dossier run id | one per (step, document) | documents, cache hits, model calls, failed |
| `dossier eval` | one, linked to the gold set's dataset (R11.7) | the judge's calls, if any | `accuracy/<field>`, `accuracy/overall` |
| `dossier sync` | one | none | `<source>/known`, `/changed`, `/new`, `/fetched`, `/failed`; `changes.json` attached (R11.6) |
| `dossier convert` | one | none | `<source>/held`, `/converted`, `/cached`, `/failed` |
| `dossier calibrate` | one, per gold set | one per sample case | `judge/<field>/agreement`, `judge/<field>/cases` |
| `dossier run --plan`, `--replay` | none | none | none |
| `dossier dataset publish` | none | none | none; it publishes a dataset rather than recording a run (spec 012) |

Metric names use `/` so MLflow's UI groups them: every field's accuracy under
`accuracy/`, every count of one source under its id. Accuracy is recorded as the
percentage the report prints -- `75.0`, not `0.75` -- for the reason above, and a
judge's agreement likewise: `100.0`, the figure `dossier calibrate` prints.

A trace is one (step, document), the unit of a cache key. Following `INC-4821`
through the pipeline is a filter on the `dossier.document` tag; every `verify`
failure is a filter on `dossier.step` and status. A cache hit is still a trace,
with no LLM span in it: seeing that a document cost nothing is information.

A calibration has no steps and no cache; its unit is one sample case, and that is
its trace. A calibration is the most experiment-shaped thing `dossier` does --
change the judge model or the rubric, measure again, compare -- and the file it
writes holds only the latest measurement (R7.14 row 2), so a judge that was tried
and rejected leaves no record on disk. The experiment is where it survives. Its
model calls are real ones, twenty per field, which until R11.5 were the only
model calls `dossier` made that no trace could see (R11.2). A trace per case
carries the verdict the reviewer gave and the one the judge gave, so the case
they disagree on is a filter rather than a re-run.

## Must hold

### R11.1 — a `dossier run` is one MLflow run, named after its run id, with one trace per (step, document)

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R011_1__a_run_records_one_trace_per_step_and_document.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract` over `INC-4821`, `INC-4822`, `INC-4901`, `INC-5455`, nothing cached | 1 MLflow run named `20260806T142203Z-4f1a`; 4 traces, each tagged `dossier.step=extract` and its document |
| 2 | the same | params: pipeline, pinned model, pipeline hash; metrics: documents 4, cache hits 0, model calls 4, failed 0; `manifest.json` attached as an artifact |
| 3 | `report`, an aggregate step | 1 trace, under document `*` |
| 4 | `INC-4821` fails validation twice | its trace has status ERROR and names the error (R6.9); the other three are OK |
| 5 | *counter-example* — `dossier run incident-audit --plan` | 0 MLflow runs, 0 traces (R4.6) |
| 6 | *counter-example* — `dossier run --replay runs/20260806T142203Z-4f1a/` | 0 MLflow runs, 0 traces; a replay reproduces a record, it does not make one (R4.7) |

### R11.2 — each model call is exactly one LLM span

The trace and `FakeModelClient`'s call count are the same claim seen twice (R5.5).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R011_2__each_model_call_is_one_llm_span.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | 4 documents, nothing cached | 4 LLM spans, equal to `fake_model.call_count` |
| 2 | `INC-4822` valid on its second attempt | 2 LLM spans in its trace; the first carries the validation error it was retried on |
| 3 | *counter-example* — the same run again, every result served from cache | 4 traces and 0 LLM spans; each stage span marked `dossier.cache=hit` with its key |

### R11.3 — a `dossier eval` is one MLflow run with one metric per scored field

Supersedes R7.9, which named the experiment after the pipeline and recorded an
eval only. The figures are the ones R7.2 prints, so the terminal and MLflow
cannot disagree.

A field whose judge may not be quoted is left out of `accuracy/overall` as well
as of its own metric. R7.5 withholds that number because a percentage reads as
evidence whether or not it was earned, and an overall that quietly absorbed the
same field would hand it back in the figure most people read first.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/unit/test_R011_3__an_eval_records_one_metric_per_field.py`, `tests/acceptance/test_R011_3__eval_records_its_scores_to_mlflow.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier eval incident-audit --gold gold/incidents` over the scoring example | `accuracy/loss_amount` 100.0, `accuracy/resolution_date` 75.0, `accuracy/severity` 100.0, `accuracy/affected_systems` 75.0, `accuracy/root_cause` 50.0, `accuracy/overall` 80.0 |
| 2 | the same | params: the pinned model and gold set `incidents`; tags: the gold set's full 64-character hash (R0.7) and `dossier.run_id` of the run it scored |
| 3 | a `root_cause` judge at agreement 0.91, threshold 0.85 | param `judge/root_cause/agreement` 0.91, with its judge model identifier (R7.11 row 2) |
| 4 | the judge at 0.78 against 0.85 (R7.5) | no `accuracy/root_cause` metric, and it is left out of `accuracy/overall` as well; a tag says the judge was ineligible, and why |
| 5 | *counter-example* — a gold set covering only `severity` | one field metric; no zero is recorded for fields nobody verified (R7.3 row 4) |

### R11.4 — a `dossier sync` or `dossier convert` is one MLflow run of per-source counts, with no traces

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.count_metrics`)
- **Proved by:** `tests/unit/test_R011_4__sync_and_convert_record_per_source_counts.py`, `tests/acceptance/test_R011_4__sync_and_convert_record_to_mlflow.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a sync where `incidents-jira` holds 420 items, 18 changed and 2 new | `incidents-jira/known` 420, `/changed` 18, `/new` 2, `/fetched` 20 -- the numbers R2.13 prints |
| 2 | a convert of `incidents-manual` holding three documents, none converted | `incidents-manual/held` 3, `/converted` 3, `/cached` 0 (R8.8) |
| 3 | *counter-example* — `procedures-confluence` where nothing changed | recorded with its zeros, not omitted; a missing source is indistinguishable from a skipped one (R2.13) |

### R11.5 — a `dossier calibrate` is one MLflow run per gold set holding what it measured, with one trace per sample case

The figures are the ones R7.14 writes to `calibrations/<field>.json` and the
terminal prints, so the file, the terminal and MLflow cannot disagree. What the
run adds is what the file cannot hold: every measurement rather than the latest,
and the case-by-case verdicts behind the agreement figure.

The bar is not part of the measurement. R7.14 row 5 says a calibration never
reads `judge.yaml`, and a run that recorded the threshold beside the agreement
would read as having applied it. The two meet on the eval that gates (R11.3
row 4), and nowhere else.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.calibrate_field`)
- **Proved by:** `tests/unit/test_R011_5__a_calibration_records_one_run_with_one_trace_per_case.py`, `tests/acceptance/test_R011_5__calibrate_records_to_mlflow.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier calibrate incident-audit --gold gold/incidents`, whose `samples/root_cause.jsonl` holds 20 cases, judged by `openai:gpt-5.4-mini` | 1 MLflow run in `dossier-audit/incident-audit/calibrate`, tagged `dossier.kind=calibrate`, `dossier.pipeline=incident-audit` and the gold set's full 64-character hash (R0.7); params `judge/root_cause/model` `openai:gpt-5.4-mini` and `judge/root_cause/rubric` `f7a2d9c4`; metrics `judge/root_cause/agreement` 100.0 and `judge/root_cause/cases` 20 -- the figures the terminal line prints and the file holds |
| 2 | the same | 20 traces, one per sample case, each tagged `dossier.document` and carrying the verdict the reviewer gave and the verdict the judge gave; `INC-4830`'s reads unsupported by both (R7.12); each trace holds exactly one LLM span (R11.2) |
| 3 | the pipeline's model changed to `ollama:qwen2.5:7b@sha256:7f3c29a1`, calibrated again | a second run beside the first in the same experiment, with its own model param and agreement; the file holds only the latest measurement (R7.14 row 2), the experiment holds both |
| 4 | *counter-example* — a sample of 19 cases | refused (R7.14 row 3); 0 MLflow runs, 0 traces. Nothing was measured, so there is nothing to record |
| 5 | *counter-example* — `gold/incidents/judge.yaml` declaring `root_cause: 0.95` | not on the run, as no param, metric or tag; a calibration never reads the bar (R7.14 row 5), and the run that records both the figure and whether it cleared the bar is the eval's (R11.3 row 4) |

### R11.6 — a `dossier sync` attaches `changes.json`, naming what the terminal named

The items R2.18 and R2.20 print, as one artifact: `changed` as a list of
`{source, key, from, to}` and `tombstoned` as a list of `{source, key}`. It is
the report's own list handed to the tracker, never a second reading of the
ledger -- the principle this spec opens with.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync`)
- **Proved by:** `tests/unit/test_R011_6__a_sync_attaches_the_changes_it_named.py`, `tests/acceptance/test_R011_6__sync_records_the_changes_it_named.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4822` repointed `0e52dd18` to `77c1b40a`, `INC-4821` tombstoned | `changes.json` holds `changed: [{incidents-jira, INC-4822, 0e52dd18…, 77c1b40a…}]` and `tombstoned: [{incidents-jira, INC-4821}]`, full hashes |
| 2 | a sync where nothing changed | `changes.json` attached with two empty lists; an absent artifact is indistinguishable from a sync that never ran (R11.4 row 3) |
| 3 | *counter-example* — `dossier run --plan` after that sync | no MLflow run, so nothing attached (R11.1 row 5); the record belongs to the command that fetched |

### R11.7 — a `dossier eval` links its MLflow run to the dataset of the gold set it scored, and names a stale one

The dataset spec 012 publishes, logged as the run's input, so the run and the
answers it was measured against are one click apart rather than one hash lookup.
The link is a record and never an input: the gold set on disk is what was scored
(R12.4), so a dataset that does not match it is *named*, not obeyed, and a
dataset that cannot be read at all costs the eval nothing (R10.6).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.start_eval`)
- **Proved by:** `tests/unit/test_R011_7__an_eval_links_the_dataset_it_scored_against.py`, `tests/acceptance/test_R011_7__eval_links_its_dataset_in_mlflow.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold/incidents` published, then `dossier eval incident-audit --gold gold/incidents` | the dataset `incidents` logged as an input of the eval run, beside the gold hash tag and per-field metrics R11.3 already records |
| 2 | the gold set edited since publishing — published `3b7e1d90`, scored `9c4f21a8` | linked anyway, tagged `dossier.dataset_stale=true` with both hashes; the terminal says which is which and names `dossier dataset publish`. The figures are the edited set's, because that is what was scored |
| 3 | no dataset published for `gold/incidents` | the eval records exactly what R11.3 says and no input; a missing dataset is not an error, and nothing about the score changed |
| 4 | the dataset unreadable — the server answers the run's calls and 500s on the dataset | recorded without the link, one line saying so; a lost record never changes a command's outcome (R10.6) |
| 5 | *counter-example* — `dossier eval incident-audit --gold gold/incidents --compare A B` | no MLflow run and so no link; a comparison reads two runs each recorded when they ran (R7.8) |
