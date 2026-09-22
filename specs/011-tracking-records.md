# 011 — What each command records to MLflow

**Status:** Partially implemented
**Rules:** R11.1 – R11.16

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
| `dossier eval --compare a b` | one | none | `a/<field>`, `b/<field>`, `delta/<field>`, and the same three for the overall (R11.8) |
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

A record also says what it *is*, not only what it measured. An eval carries the
version of everything it scored -- the pipeline hash, each step's prompt and
schema hashes, the converters, read off the manifest of the run it reproduced
(R11.11) -- a description generated from the figures it printed (R11.12), and the
per-document detail the terminal showed (R11.14). A comparison adds the one thing
a person opens it to find: which steps actually differ between the two runs
(R11.13). None of it is a second computation. Every value is read from a manifest
the run wrote or restated from a line the command printed.

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
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold/incidents` published, then `dossier eval incident-audit --gold gold/incidents` | the dataset `incidents` logged as an input of the eval run, beside the gold hash tag and per-field metrics R11.3 already records |
| 2 | the gold set edited since publishing — published `3b7e1d90`, scored `9c4f21a8` | linked anyway, tagged `dossier.dataset_stale=true` with both hashes; the terminal says which is which and names `dossier dataset publish`. The figures are the edited set's, because that is what was scored |
| 3 | no dataset published for `gold/incidents` | the eval records exactly what R11.3 says and no input; a missing dataset is not an error, and nothing about the score changed |
| 4 | the dataset unreadable — the server answers the run's calls and 500s on the dataset | recorded without the link, one line saying so; a lost record never changes a command's outcome (R10.6) |
| 5 | *counter-example* — `dossier run --replay runs/20260806T142203Z-4f1a/` | no MLflow run at all, so nothing to link (R11.1 row 6). A replay reproduces a record rather than making one, and a dataset link is a record. A comparison *does* open a run and *does* link the dataset, which is R11.10 |

### R11.8 — a `dossier eval --compare a b` is one MLflow run of per-field deltas, with no traces

The figures R7.8 prints, in a run of their own. Until now a comparison recorded
nothing, on the reasoning that it reads two runs each already recorded when they
ran -- true of the two *scores*, and not true of the **delta**, which is a figure
neither run holds and the only one the change gate exists to produce. A regression
found in a terminal that has since scrolled away is the failure this prevents, and
it is the same one every other rule in this spec prevents.

Its own experiment kind, `compare`, because an experiment should hold runs that are
comparable with one another (R10.2) and a delta is not an accuracy: `accuracy/severity`
and `delta/severity` in one experiment would sit in the same column reading as the
same kind of number. `{gold}` renders for it, as it does for an eval, and
`DOSSIER_MLFLOW_EXPERIMENT_COMPARE` overrides it.

No traces: a comparison reproduces both runs from their manifests and caches and
asks no model (R7.10), so there is no (step, document) unit of work to trace. The
two runs it reads have their own traces, recorded when they ran.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.record_comparison`)
- **Proved by:** `tests/unit/test_R011_8__a_comparison_records_one_run_of_deltas.py`, `tests/acceptance/test_R011_8__compare_records_its_deltas_to_mlflow.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier eval incident-audit --gold gold/incidents --compare 20260806T142203Z-4f1a 20260907T090000Z-bbbb` over the comparison example | 1 MLflow run in `dossier-audit/incident-audit/compare`, tagged `dossier.kind=compare`; metrics `a/affected_systems` 75.0, `b/affected_systems` 50.0, `delta/affected_systems` -25.0, and the same three for every other field and for the overall -- the figures the table prints |
| 2 | the same | params naming both run ids and the model each pinned, and the gold set's full 64-character hash as a tag (R0.7); 0 traces |
| 3 | `severity` at 100.0% in both runs | `delta/severity` 0.0, recorded. A field omitted because it did not move is indistinguishable from one nobody scored (R7.8 row 4) |
| 4 | *counter-example* — run `b` covering a fifth document `INC-5102` that `a` did not | refused (R7.8 row 3); 0 MLflow runs. Nothing was compared, so there is nothing to record -- as a refused calibration records nothing (R11.5 row 4) |

### R11.9 — the fields a comparison regressed are named on its run

The one thing a person opens a comparison to find. R7.8 flags a regression in the
terminal; this is the same flag where it can be filtered on months later, which is
the difference between "which change broke `affected_systems`" being a query and
being an archaeology exercise.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.regressed`)
- **Proved by:** `tests/unit/test_R011_9__a_comparison_names_the_fields_that_regressed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `affected_systems` moving 75.0% to 50.0% while the overall moves 80.0% to 90.0% | `dossier.regressed` is `affected_systems`; the improving overall does not hide it, which is R7.8 row 2 seen in MLflow |
| 2 | two fields regressed | both named, in the order the report lists them, so the tag reads as the report does |
| 3 | *counter-example* — a comparison where no field moved down | `dossier.regressed` present and empty. An absent tag is indistinguishable from a comparison recorded before this rule existed, as an absent `changes.json` is from a sync that never ran (R11.6 row 2) |

### R11.10 — a comparison links the dataset of the gold set it scored

The same link an eval makes (R11.7), on the other command that scores against a
gold set -- so "every run measured against these answers" is one query in MLflow
rather than one per command. A stale dataset is named here as it is there, and for
the same reason: the figures came from the files (R12.4).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.record_comparison`)
- **Proved by:** `tests/acceptance/test_R011_10__compare_links_its_dataset_in_mlflow.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold/incidents` published, then a comparison over it | the dataset `incidents` logged as an input of the comparison's run, beside the deltas |
| 2 | the gold set edited since publishing | linked and tagged `dossier.dataset_stale=true`, the terminal naming both hashes (R11.7 row 2) |
| 3 | *counter-example* — no dataset published for `gold/incidents` | the comparison records its deltas and links nothing; a missing dataset is not an error (R11.7 row 3) |

### R11.11 — an eval records the version of everything it scored, read from the manifest

An eval records the model and the gold set (R11.3 row 2) and nothing else about
*what produced the answers*. So two evals five points apart in MLflow are two
figures with no stated cause: which prompt, which schema, which converter, which
rubric. The manifest of the run being scored holds all four, and an eval already
reads it to reproduce the run.

Read, never recomputed. A converter pinned at `1.3.0` in the manifest is recorded
as `1.3.0` on a machine where `1.4.0` is installed, because the record describes
the run and not the machine that scored it (R4.9).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.version_params`)
- **Proved by:** `tests/unit/test_R011_11__an_eval_records_the_version_of_what_it_scored.py`, `tests/acceptance/test_R011_11__eval_records_what_produced_what_it_scored.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier eval incident-audit --gold gold/incidents` over run `20260806T142203Z-4f1a` | params `pipeline_hash=2f60a7d3`, `prompt/verify=0e52dd18`, `schema/extract=6e0d4b27`, `converters=markdown-text 1.0.0`, `documents=4`, `dossier_version`, `scored_at=2026-08-06T14:22:03Z` |
| 2 | a judged `root_cause` | `judge/root_cause/rubric=f7a2d9c4` beside the model and agreement R11.3 row 3 already records: an edit to the rubric is visible on the eval that used it, as it is on the calibration (R11.5) |
| 3 | `--compare 20260806T142203Z-4f1a 20260907T090000Z-bbbb` | the same params under `a/` and `b/`, as `a/model` and `b/model` already are: `a/pipeline_hash=2f60a7d3`, `b/pipeline_hash=8ad3e115` |
| 4 | a step whose declaration generates a schema (R6.12) | its `generated_schema/<step>` hash too, `d24c86e1`; it is in the stage key, so it is part of what produced the answer |
| 5 | *counter-example* — the manifest pins `pdf-markdown 1.3.0`, `1.4.0` is installed | `1.3.0` recorded. A value recomputed here would describe the scoring machine, and two evals of one run on two laptops would disagree |

### R11.12 — an eval and a comparison carry a description generated from the figures they printed

MLflow's Description is the first thing on a run's page and has been empty on
every record dossier has written. It is the one field that can say, without a
click, what this run was and what it found.

Generated, never authored: every sentence restates a line the command printed. A
figure appearing only in the description would be a second way of arriving at
one, which is what this spec exists to forbid. Written when the run closes rather
than when it opens, because the figures do not exist until the scoring is done.

Carried in `mlflow.note.content`, one of the four tags R10.12 permits.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.description`)
- **Proved by:** `tests/unit/test_R011_12__a_record_describes_what_it_measured.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | the scoring example (R7.2) | the description holds `overall 80.0% over 5 fields`, `root_cause 50.0% — weakest`, the run id scored, the pinned model, and `gold incidents 3b7e1d90` |
| 2 | `root_cause` withheld because its calibration is stale (R7.15) | the description names the field and the reason, as the terminal line does, and states no accuracy for it |
| 3 | the comparison example (R7.8) | `overall 80.0% -> 90.0% (+10.0)`, `regressed: affected_systems`, both run ids and both pinned models |
| 4 | *counter-example* — a comparison refused because the two runs cover different documents (R7.8 row 3) | no run is opened, so there is no description. Nothing was measured |
| 5 | *counter-example* — the same eval run twice, with tracking on and off | byte-identical manifests and stage keys (R10.4). A description is a record, and a record is not an input |

### R11.13 — a comparison names the steps that differ between the two runs it compared

The question a change gate is opened with is "what changed?", and until now the
record answered "these five numbers did". Which prompt moved, which model, which
documents -- the cause of the delta -- was in neither run's record and had to be
reconstructed by diffing two manifests by hand.

`dossier run --plan` already computes exactly this, over exactly these inputs
(R4.12). The comparison runs the same decision over the two manifests it has
already read, and records what it returns.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.plan.diff`)
- **Proved by:** `tests/unit/test_R011_13__a_comparison_names_what_differs_between_its_runs.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | run `b` produced after the `verify` prompt changed | `dossier.changed_steps=verify (prompt changed)`; the delta has a stated cause on the same page as the delta |
| 2 | the pinned model changed between the two runs | every step named `(model changed)`: the pin belongs to the whole plan, not to one step (R4.12) |
| 3 | `INC-4822` re-fetched at a new snapshot between the runs | `extract (documents changed)`, and the steps below it `(upstream changed)` -- the propagation R4.12 walks |
| 4 | *counter-example* — both runs at pipeline hash `2f60a7d3`, over the same snapshots | `dossier.changed_steps` present and empty. An absent tag is indistinguishable from a comparison recorded before this rule existed (R11.9 row 3) |
| 5 | *counter-example* — run `b` is a run of `postmortem-review` | already refused before anything is recorded; a comparison across pipelines is not a comparison |

### R11.14 — an eval and a comparison attach the per-document detail the terminal printed

An eval prints one line per miss -- `INC-4901 resolution_date 2026-08-12 does not
match 2026-08-11` -- and records a percentage. The percentage says a field is at
75.0%; the lines say which document and why, which is the difference between
knowing a field is weak and knowing what to do about it. They live only in the
terminal, and R0.11's run directory does not hold them, because a score is not
something a run produced.

Composed from what was printed, as `changes.json` is (R11.6), and sorted, so the
bytes do not depend on the order anything happened to run in (R0.4).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/unit/test_R011_14__an_eval_attaches_the_detail_it_printed.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | the scoring example (R7.2) | `scores.json` attached: 20 entries, four documents by five fields, each with its verdict and the detail the terminal printed beside it |
| 2 | `INC-4822`'s `root_cause`, where gold abstains | its entry reads `incorrect; gold abstains` -- the words R7.3 printed, not a restatement of them |
| 3 | the comparison example (R7.8) | `deltas.md` attached, holding the table the terminal printed, `affected_systems` marked as the regression |
| 4 | a judged field under `DOSSIER_MLFLOW_CAPTURE=hashes` | the verdict is in the entry and the judge's evidence is not: the evidence quotes the document (R10.8) |
| 5 | *counter-example* — a field withheld (R7.15) | its entry says which of missing, short or stale, and no percentage. A withheld field is named, never omitted |
| 6 | *counter-example* — the same eval with tracking off | nothing under `runs/` or `.dossier/` differs by a byte; the artifact is built from what was printed and written nowhere else (R10.4) |

### R11.15 — the judge's LLM span carries what a stage span carries

A stage's span holds the rendered prompt and the model's reply under `full`, and
their hashes under `hashes` (R10.8). A judge's span holds its model identifier
and nothing else, so the one question in `dossier` whose answer is a *judgement*
is the one call nobody can read back. The verdict and the evidence are in the
cache artifact, which is on the scoring machine and not on the server.

The same payload, under the same setting, for the same reason: anyone who has the
documents can check what was asked, and nobody who has only the server can read
them.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.span_payload`)
- **Proved by:** `tests/unit/test_R011_15__a_judge_span_carries_what_a_stage_span_carries.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `full`, a miss on `INC-4830` candidate `rc-01` | the span holds the rendered judge question and the reply, as R10.8 row 1 gives a stage |
| 2 | `DOSSIER_MLFLOW_CAPTURE=hashes` | the judge prompt hash, the input hashes and the verdict's cache key; no words of the document and none of the candidate |
| 3 | either setting | the field, the document, the judge model and the verdict: they identify, they do not disclose (R10.8 row 4) |
| 4 | *counter-example* — the verdict served from cache | a trace with no LLM span at all, as R7.18 already has it. There was no call, so there is nothing to carry |

### R11.16 — a judge's verdict is an assessment on the trace the eval already opened

An eval opens one trace per judged (field, document) (R7.18 row 5). MLflow's
Evaluations view reads assessments on traces, and dossier attaches none, so the
view is empty for the one part of scoring that is not arithmetic.

Recorded, never computed. `mlflow.genai.evaluate` would have MLflow arrive at a
verdict of its own from the same material, which is the second-way-of-computing
this spec forbids; an assessment is a projection of a verdict dossier already
reached, one way only, as a published dataset is (R12.4).

On every judged verdict, whether the judge was asked or the cache answered: the
verdict is what the eval scored either way, and an assessment that appeared only
on a cache miss would make a second eval of one run look like it judged nothing.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/unit/test_R011_16__a_judge_verdict_is_an_assessment.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause · INC-4830`, candidate `rc-01`, judged supported | an assessment named `root_cause`, value `true`, rationale the judge's evidence, sourced to the judge model |
| 2 | candidate `rc-02`, the planted claim (R7.12) | value `false`: the case that tells a working judge from one that agrees with everything is a filter in the UI |
| 3 | the same eval run a second time, every verdict from cache | the same assessments, on the traces of the second run. A verdict that cost nothing is still the verdict that was scored |
| 4 | `DOSSIER_MLFLOW_CAPTURE=hashes` | the value is recorded and the rationale is not; the evidence quotes the document (R10.8) |
| 5 | *counter-example* — a field withheld (R7.15) | no assessment, because it was never judged: nothing is measured for a number nobody may print (R7.17) |
| 6 | *counter-example* — `mlflow.genai.evaluate` | never called. Every value on a trace is one `dossier` computed and printed |
