# 011 — What each command records to MLflow

**Status:** Implemented
**Rules:** R11.1 – R11.26

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
| `dossier sync` | one | none | `<source>/known`, `/changed`, `/new`, `/returned`, `/fetched`, `/failed` (R11.25); `changes.json` attached (R11.6, R11.24) |
| `dossier convert` | one | none | `<source>/held`, `/converted`, `/cached`, `/failed`, `/left_out` (R11.26) |
| `dossier calibrate` | one, per gold set | one per sample case | `judge/<field>/agreement`, `judge/<field>/cases` |
| `dossier eval --compare a b` | one | none | `a/<field>`, `b/<field>`, `delta/<field>`, and the same three for the overall (R11.8) |
| `dossier run --plan`, `--replay` | none | none | none |
| `dossier dataset publish` | none | none | none; it publishes a dataset rather than recording a run (spec 012) |

Metric names use `/` so MLflow's UI groups them: every field's accuracy under
`accuracy/`, every count of one source under its id. Accuracy is recorded as the
percentage the report prints -- `75.0`, not `0.75` -- for the reason above, and a
judge's agreement likewise: `100.0`, the figure `dossier calibrate` prints.

Every one of those records also carries a description generated from the lines
the command printed (R11.12, R11.17) and a param naming the `dossier` that wrote
it (R11.19). They are the two fields a person reads before any metric, and both
were blank on every record dossier had written.

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
| 2 | a sync where nothing changed | `changes.json` attached with every list empty; an absent artifact is indistinguishable from a sync that never ran (R11.4 row 3) |
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
- **Layer:** domain (`dossier.domain.tracking.eval_description`, `.comparison_description`)
- **Proved by:** `tests/unit/test_R011_12__a_record_describes_what_it_measured.py`, `tests/acceptance/test_R011_12__eval_describes_itself_in_mlflow.py`
- **Status:** MET

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
- **Layer:** domain (`dossier.domain.plan.changed_steps`)
- **Proved by:** `tests/unit/test_R011_13__a_comparison_names_what_differs_between_its_runs.py`, `tests/acceptance/test_R011_13__compare_names_what_changed_between_its_runs.py`
- **Status:** MET

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
- **Proved by:** `tests/unit/test_R011_14__an_eval_attaches_the_detail_it_printed.py`, `tests/acceptance/test_R011_14__eval_attaches_what_the_terminal_showed.py`
- **Status:** MET

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
- **Layer:** application (`dossier.application.eval.judge_span`)
- **Proved by:** `tests/unit/test_R011_15__a_judge_span_carries_what_a_stage_span_carries.py`, `tests/acceptance/test_R011_15__the_judge_call_is_readable_in_mlflow.py`
- **Status:** MET

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
- **Proved by:** `tests/acceptance/test_R011_16__a_judge_verdict_is_an_assessment.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause · INC-4830`, candidate `rc-01`, judged supported | an assessment named `root_cause`, value `true`, rationale the judge's evidence, sourced to the judge model |
| 2 | candidate `rc-02`, the planted claim (R7.12) | value `false`: the case that tells a working judge from one that agrees with everything is a filter in the UI |
| 3 | the same eval run a second time, every verdict from cache | the same assessments, on the traces of the second run. A verdict that cost nothing is still the verdict that was scored |
| 4 | `DOSSIER_MLFLOW_CAPTURE=hashes` | the value is recorded and the rationale is not; the evidence quotes the document (R10.8) |
| 5 | *counter-example* — a field withheld (R7.15) | no assessment, because it was never judged: nothing is measured for a number nobody may print (R7.17) |
| 6 | *counter-example* — `mlflow.genai.evaluate` | never called. Every value on a trace is one `dossier` computed and printed |

### R11.17 — every command's record describes itself from the lines it printed

R11.12 gave a description to the two commands that score. The four that do the
work -- `run`, `sync`, `convert`, `calibrate` -- open a record whose Description
is the first thing on its page and is empty on every one of them. Eight
`sync incident-audit` records in a list are eight identical rows, and which one
fetched the twenty documents is a click each.

The same construction, for the same reason: generated and never authored, every
line restating one the command printed, written when the run closes because none
of the counts exist until the work is done. Carried in `mlflow.note.content`,
one of the four tags R10.12 permits.

Verbatim rather than restated. The description holds the command's own lines with
their indentation stripped, so a figure that moves in the terminal and not in the
record fails a test instead of drifting quietly -- which is the failure mode this
spec's opening paragraph is about, in the one place a second copy of a line is
unavoidable.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.run_description`, `.sync_description`, `.convert_description`, `.calibration_description`)
- **Proved by:** `tests/unit/test_R011_17__every_command_describes_what_it_did.py`, `tests/acceptance/test_R011_17__every_record_describes_itself_in_mlflow.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` over 4 documents and 3 steps, `verify` serving all 4 from cache | `run 20260806T142203Z-4f1a · incident-audit`, `model anthropic:claude-sonnet-4-5-20250929 · pipeline 2f60a7d3`, then `verify: 4 document(s) · 4 from cache · 0 failed` -- the step line R6.9 prints, verbatim |
| 2 | that run with `extract` failing on `INC-5044` and two findings in `verify` | described all the same, `extract` naming its failure and `verify` its findings. A description written only on success would make a failure look like a command nobody ran (R8.6) |
| 3 | the sync of R11.4 row 1 | `incidents-jira  420 known · 18 changed · 2 new -> 20 fetched` and `ledger updated · 20 new snapshots · 0 tombstoned` -- the source line and the ledger line (R2.13, R2.18) |
| 4 | the convert of R11.4 row 2 | `incidents-manual  3 held · 3 converted · 0 cached` and `cache updated · 3 converted · 0 cached` (R8.8) |
| 5 | the calibration of R11.5 row 1 | `calibrate incident-audit · gold incidents 3b7e1d90` and `root_cause 100.0% agreement over 20 cases · openai:gpt-5.4-mini` -- the line the terminal prints (R7.14) |
| 6 | *counter-example* — a run that stops at its first cache miss on an unreachable model (R9.2 row 3) | the record closes `FAILED` with no description. Nothing was counted, and a description is a restatement of counts |
| 7 | *counter-example* — the same run twice, tracking on and off | byte-identical manifests and stage keys (R10.4). A description is a record, and a record is not an input |

### R11.18 — a `dossier run` records the version of everything it used

R11.11 gave the eval that scores a run the prompt, schema, converter and
generated-schema versions, read off the manifest. The run that *wrote* that
manifest records three params -- its pipeline, its model and its pipeline hash --
so two runs of one pipeline sit side by side in MLflow's comparison with no way
to see which prompt moved between them. The evals of those same two runs answer
it, and the runs themselves do not.

The same function over the same plan, at the moment it is resolved rather than at
the moment it is read back. `documents` lands as a param beside the metric of the
same name R11.1 already records: the plan's document count is an input to the run
and the metric is what it processed, equal by construction and read in different
places.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run.execute`)
- **Proved by:** `tests/acceptance/test_R011_18__a_run_records_what_produced_it.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` at pipeline hash `2f60a7d3` | params `prompt/verify=0e52dd18`, `schema/extract=6e0d4b27`, `converters=markdown-text 1.0.0`, `documents=4`, beside the three it already records |
| 2 | the `verify` prompt edited and the pipeline run again | `prompt/verify` differs between the two records, and MLflow's run comparison names the one param that moved |
| 3 | a step whose declaration generates a schema (R6.12) | `generated_schema/<step>=d24c86e1`, as the eval records it (R11.11 row 4) |
| 4 | *counter-example* — `dossier run --plan` | no MLflow run at all (R11.1 row 5). Params of a plan nobody executed would be a record of work that did not happen |
| 5 | *counter-example* — the eval that scores that run | the same values, read off the manifest (R11.11). Two records of one plan agree because they are one function over one set of data, not because two computations happened to match |

### R11.19 — every record says which `dossier` wrote it

`dossier_version` is a param on an eval and on none of the other five kinds. A
sync whose counts look wrong, a convert that produced different bytes, a run
whose plan resolved differently -- the first question asked of each is which
`dossier` did it, and only the eval can answer.

One param, on every run any command opens, from the installed distribution's own
metadata: the value R4.9 already writes into every manifest.

- **Kind:** deterministic
- **Layer:** application (`dossier.application`)
- **Proved by:** `tests/acceptance/test_R011_19__every_record_says_which_dossier_wrote_it.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync incident-audit` under `dossier` 0.9.0 | param `dossier_version=0.9.0` |
| 2 | `dossier run`, `convert`, `calibrate` and `eval --compare` | the same param, under the same name the eval already records it (R11.11 row 1) |
| 3 | *counter-example* — the manifest that run wrote | already holds it (R4.9). The param is a second place to read the version, never a second way of arriving at it |
| 4 | *counter-example* — tracking off | no param, and nothing under `runs/` or `.dossier/` differs by a byte (R10.4) |

### R11.20 — a run's record holds the tokens it spent, and each LLM span carries its call's tokens where MLflow reads them

The run gains two metrics beside `model_calls`, `tokens_in` and `tokens_out`:
the same sums R5.12 prints, handed to the record rather than worked out again
(this spec's first principle). Each LLM span carries its one call's count under
`mlflow.chat.tokenUsage` -- `input_tokens`, `output_tokens` and `total_tokens`
-- which is MLflow's own attribute rather than a `dossier.` one: MLflow 3 adds
every span's into its trace's `mlflow.trace.tokenUsage`, so the trace list says
what each (step, document) cost without `dossier` computing a second total.

A count is not content. It is recorded under `capture=hashes` exactly as under
`full` (R10.8): a number of tokens says nothing a hashed span must not.

A run that asked nothing spent nothing, and records `0`: a true count. A run
with a call its provider did not report records neither metric, and that span
carries no usage -- missing, not `0`, as a withheld field is missing from the
record rather than scored (R7.17).

What a judge's calls cost in `dossier eval` and `dossier calibrate` is not
claimed here; a stage's are.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`, `dossier.application.extract`)
- **Proved by:** `tests/unit/test_R011_20__a_run_records_the_tokens_it_spent.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | three documents, nothing cached, each answer costing 1204 in and 212 out | metrics `tokens_in` 3612 and `tokens_out` 636; each of the three LLM spans carries `mlflow.chat.tokenUsage` `{input_tokens: 1204, output_tokens: 212, total_tokens: 1416}` |
| 2 | `INC-4822` valid on its second attempt (R11.2 row 2) | two LLM spans in its trace, each carrying its own attempt's count; the run's metrics hold their sum |
| 3 | `DOSSIER_MLFLOW_CAPTURE=hashes` | the same usage on every span, and still no prompt or reply text (R10.8 row 2) |
| 4 | *counter-example* — the same run again, every document from cache | no LLM span (R11.2 row 3), and `tokens_in` and `tokens_out` both `0`: nothing was asked |
| 5 | *counter-example* — a provider that reports nothing (R9.18 row 4) | no `mlflow.chat.tokenUsage` on the span, and no `tokens_in` or `tokens_out` on the run: missing, not `0` |

### R11.21 — a run asking about several documents at once records each one's trace holding only its own spans, and says how many it asked at once

MLflow keeps apart traces opened on different threads. Four documents' traces,
opened at once, each from its own thread, came back from a real MLflow 3.15.1
store holding one span each, with durations MLflow measured itself: 473, 373,
274 and 174 ms for work of 0.4, 0.3, 0.2 and 0.1 s. That was checked before this
rule was written. `dossier`'s tracker did not keep them apart. It held one
current trace for the whole process, so at `N > 1` (R9.19) a span went to
whichever trace had been opened last, and `INC-4821`'s trace could show
`INC-4822`'s prompt.

So a trace is current in the thread that opened it. That changes what the
`Tracker` port promises and not what it is called with. The fake tracker keeps
the same promise, or it could not fail when the real one broke it. Nothing is
held back and replayed: each trace reaches MLflow while its document is worked
on, and is timed by MLflow, exactly as at `N = 1`.

Traces reach the server in the order their documents finish. Nothing reads that
order: MLflow lists traces by the start time it measured, and `dossier` reads
nothing back (R0.10). A trace lost on one thread is counted once, as on one
(R10.24).

The run records `concurrency` as a param, so two runs' durations are compared
knowing that one asked four documents at a time. It is a param of the record and
nothing else: like every value a record holds, it reaches no key, manifest or
provenance record (R10.4).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking`), application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R011_21__a_run_at_concurrency_records_each_document_apart.py`, `tests/unit/test_R011_21__a_trace_is_current_in_the_thread_that_opened_it.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821`, `INC-4822`, `INC-4901` at `--concurrency 3`, and a model that answers none until all three are asked | three traces, `extract · INC-4821` and the other two; each holds one LLM span, and that span's prompt is about the document its trace is tagged with |
| 2 | the same, with `INC-4822` valid on its second attempt (R11.2 row 2) | its trace holds both LLM spans, and the other two hold one each |
| 3 | the run's params | `concurrency` is `3`, and `1` when neither `--concurrency` nor `DOSSIER_CONCURRENCY` is set |
| 4 | at `--concurrency 3`, one of `INC-4822`'s own tracking calls fails (R10.6), and the server does not hold that trace either | `warning: 1 trace(s) could not be recorded`: counted once, as R10.24 row 4 counts it one at a time, and the other two not at all |
| 5 | *counter-example* — `--concurrency 3` against `--concurrency 1` over the same snapshots | the same cache keys, artifacts and provenance records apart from `run_id`; `concurrency` is in the record alone (R10.4) |

### R11.22 — a run's record, and the pipeline version it built, name the model each step was asked with

A step may be asked with its own model (R3.14). The run's `model` param stays
the pipeline's, and a step asked with its own records `model/<step>` beside its
`prompt/<step>` (R11.18). That goes in the run's params and in the version's,
and the version hash is taken over them, so a version moves when a step's model
does (R13.1). Otherwise two pipelines that differ only in `extract`'s model
would share a row in the Models tab, and "did the cheaper model cost accuracy"
would have nothing to compare.

A step asked with the pipeline's model records nothing. So a pipeline with no
step model records exactly the params, and the version hash, it recorded before
this rule. Each LLM span already names the model that answered it
(`dossier.model`). An eval reads `model/<step>` off the manifest, as it reads
the rest (R11.11).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking`, `dossier.domain.versions`), application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R011_22__a_record_names_each_steps_model.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | R3.14 row 1's run, tracked | params `model` `anthropic:claude-sonnet-4-5-20250929` and `model/extract` `ollama:qwen2.5:7b@sha256:7f3c29a1`, and no `model/verify`; `extract`'s LLM spans carry `dossier.model` `ollama:qwen2.5:7b@sha256:7f3c29a1` and `verify`'s the pipeline's |
| 2 | the pipeline version that run built | its params carry `model/extract`, and its version hash differs from that of the same pipeline with no step model |
| 3 | `extract`'s model changed to `hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b` | another version: the version hash moves, though the pipeline's `model:` and every prompt hash did not (R13.1) |
| 4 | `dossier eval` of row 1's run | the eval's params carry `model/extract`, read off the manifest (R11.11) |
| 5 | *counter-example* — no step names a model | no `model/` param on the run or the version, and the version hash is the one computed before this rule |

### R11.23 — a command that stops after opening its MLflow run closes it as FAILED

A run left `RUNNING` reads as a command still at work. In the list it looks the
same as a run that is still going, and it stays that way forever. A live
calibration against MLflow 3.15.1 left one: the model was unreachable on the
first case, the exception left `calibrate_fields` with the run open, and the
server kept an empty run named as if it were measuring. `dossier run` already
closes a stopped run as FAILED, but only in code, and no rule said any command
must.

"Stops" means anything that leaves the command before its run is closed: an
exception from a model, or an interrupt. The run is closed `FAILED`, and whatever
stopped the command then goes on exactly as before. The command exits with the
same error and the same code, because the record is about the command, and
closing it never changes what the command did.

Three commands can stop with a run open, because only three open theirs before
the work they record: `dossier run`, whose traces are written while its steps
run (R11.1); `dossier calibrate`, whose traces are written case by case
(R11.5); and `dossier eval`, whose judge's traces sit inside its run (R7.18 row
5). This rule first named two, and said an eval opened its run once its work was
done. Reading the code for R9.20 showed otherwise: an eval opens its run before
it asks the judge, so a judge nobody could reach left the run `RUNNING`. `sync`,
`convert` and a comparison do open their run once their work is done, to record
what it came to (R11.4, R11.8). So nothing that stops their work can leave a run
open.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.calibrate_fields`, `dossier.application.run.execute`), cli (`dossier.cli.main.eval_`)
- **Proved by:** `tests/unit/test_R011_23__a_stopped_command_closes_its_run_as_failed.py`, `tests/acceptance/test_R011_23__an_eval_that_stops_closes_its_run_as_failed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier calibrate incident-audit --gold gold/incidents`, the judge unreachable on the first case | the calibrate run ends `FAILED`; the command still fails with the model's error |
| 2 | the same calibration, interrupted on the eleventh case | the calibrate run ends `FAILED`, and the interrupt goes on |
| 3 | `dossier run incident-audit`, the model unreachable | the run ends `FAILED` -- already true of the code, and now stated |
| 4 | *counter-example* — `dossier sync incident-audit`, interrupted inside a source | no run at all: a sync opens its run only once its sources have answered, to record their counts (R11.4), so there is nothing to close |
| 5 | *counter-example* — `dossier calibrate` on a 19-case sample | no run at all: refused before one was opened (R11.5 row 4) |
| 6 | *counter-example* — closing the run fails too, the server gone | the command's own error is the one it fails with; a lost record never changes a command's outcome (R10.6) |
| 7 | `dossier eval incident-audit --gold gold/incidents`, a `root_cause` verdict not in the cache, and the judge unreachable | the eval run ends `FAILED`; the command still fails with R9.20's line and exit 2 |
| 8 | the same eval, interrupted while the judge is asked | the eval run ends `FAILED`, and the interrupt goes on |
| 9 | *counter-example* — `dossier eval incident-audit --gold gold/incidents --compare 20260806T142203Z-4f1a 20260907T090000Z-bbbb`, the judge unreachable | no run at all: a comparison opens its run only once both sides are scored (R11.8 row 4), so there is nothing to close |

### R11.24 — a sync's `changes.json` names each item that came back, under `returned`

R11.6 hands over what R2.18 and R2.20 print. R2.25 added a third kind of
line under a source, and the record did not carry it: a sync that revived
`audit-note.pdf` named it in the terminal, and its `changes.json` held two empty
lists. That record says nothing happened.

`returned` is a list of `{source, key}`, beside `changed` and `tombstoned`. An
item that came back with other bytes than it held also carries `from` and `to`,
the two addresses its terminal line prints. An item that came back unchanged
carries neither, because its line has none. It stays out of `changed`, as it
does in the terminal: `changed` lists items that were known.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.sync.changes_artifact`)
- **Proved by:** `tests/unit/test_R011_24__changes_json_names_what_came_back.py`, `tests/acceptance/test_R011_24__sync_records_what_came_back.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `audit-note.pdf` restored to `incidents-manual`'s folder with the bytes it had (R2.25 row 1) | `returned: [{source: incidents-manual, key: audit-note.pdf}]`, with no `from` or `to`; `changed` and `tombstoned` empty |
| 2 | `INC-4821` back in `incidents-jira` with other bytes, held `0e52dd18…`, now `77c1b40a…` (R2.25 row 2) | `returned: [{incidents-jira, INC-4821, from 0e52dd18…, to 77c1b40a…}]`, full hashes; `changed` stays empty |
| 3 | *counter-example* — a sync where nothing came back | `returned: []`, present and empty (R11.6 row 2's reason) |

### R11.25 — a `dossier sync` records `<source>/returned` beside the other counts

R2.25 found that `known`, `changed` and `new` do not account for everything
`fetched` counts unless `returned` is beside them. A record without it reads the
way the terminal line did before R2.25: `/fetched` 3 against `/known` 2,
`/changed` 0 and `/new` 0. The terminal prints `returned` only when there is one
(R2.13's shape). The metric is recorded at zero as well, because R11.4 row 3
records a source's zeros: a missing count reads the same as one never measured.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.count_metrics`)
- **Proved by:** `tests/unit/test_R011_25__a_sync_counts_what_came_back.py`, `tests/acceptance/test_R011_25__sync_records_the_returned_count.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the sync of R2.25 row 1: `incidents-manual  2 known · 0 changed · 0 new · 1 returned -> 3 fetched` | `incidents-manual/known` 2, `/changed` 0, `/new` 0, `/returned` 1, `/fetched` 3 -- the numbers the line prints |
| 2 | `INC-4821` back in `incidents-jira` with other bytes | `incidents-jira/returned` 1 and `/changed` 0, as the line counts them (R2.25 row 2) |
| 3 | *counter-example* — a sync where nothing came back | `/returned` 0, recorded rather than omitted (R11.4 row 3) |

### R11.26 — a `dossier convert` records `<source>/left_out` beside the other counts

A document R8.27 leaves out is counted in `held` and printed as `· 1 left out`,
but the record did not carry that count. `/held` 3 against `/converted` 2,
`/cached` 0 and `/failed` 0 leaves one document unaccounted for. That is R11.25's
gap on the convert side. The count is recorded at zero like every other (R11.4
row 3), though the terminal prints it only when there is one.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.count_metrics`)
- **Proved by:** `tests/unit/test_R011_26__a_convert_counts_what_it_left_out.py`, `tests/acceptance/test_R011_26__convert_records_the_left_out_count.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the folder of R8.27 row 1, `convert: {application/json: []}` | `3 held · 2 converted · 0 cached · 1 left out`, and `<source>/held` 3, `/converted` 2, `/cached` 0, `/left_out` 1, `/failed` 0 |
| 2 | the same folder converted again | `/converted` 0, `/cached` 2 and `/left_out` 1: a document left out is left out on every run, and never counted as cached |
| 3 | *counter-example* — the same folder declaring no `convert:` | `PLAY-4006-indexer-alerts.json` fails (R8.25): `/failed` 1, `/left_out` 0 |
