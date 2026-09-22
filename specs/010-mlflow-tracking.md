# 010 — MLflow tracking: the switch, where records go, and what tracking may not do

**Status:** Partially implemented
**Rules:** R10.1 – R10.12

## Purpose

`dossier` records what each command did to MLflow, so that a slow step, a
retried document or a regressed field can be inspected after the fact rather
than reconstructed from a terminal that has since scrolled away.

Tracking **observes** a run; it is never an input to one. Turning it on or off
changes no output, and nothing read back from MLflow ever enters a key, a
manifest or a score (R0.10). Without that, a run's result would depend on
whether a server happened to be up, and R0.5's promise -- a cache hit means
nothing relevant changed -- would quietly acquire an exception.

What each command records is spec 011. This spec is whether tracking is on,
where its records go, and what it may not do.

## Configuration

Per machine, read from the environment or `.env` (R9.11), never from committed
configuration -- the same reasoning as a model endpoint (R9.2). Whether a laptop
records its runs is not a property of the pipeline.

| Variable | Values | Default |
|---|---|---|
| `DOSSIER_MLFLOW_ENABLED` | `true` / `false` | `false` |
| `DOSSIER_MLFLOW_TRACKING_URI` | a URL | none; `.env.example` says `http://localhost:5000` |
| `DOSSIER_MLFLOW_EXPERIMENT` | a template | `dossier-audit/{pipeline}/{kind}` |
| `DOSSIER_MLFLOW_EXPERIMENT_SYNC`, `_CONVERT`, `_RUN`, `_EVAL`, `_CALIBRATE`, `_COMPARE` | a template | falls back to `DOSSIER_MLFLOW_EXPERIMENT` |
| `DOSSIER_MLFLOW_CAPTURE` | `full` / `hashes` | `full` |
| `DOSSIER_MLFLOW_RUN_NAME_SYNC`, `_CONVERT`, `_RUN`, `_EVAL`, `_CALIBRATE`, `_COMPARE` | a template | the default for that kind (R10.10) |
| `DOSSIER_MLFLOW_RUN_PREFIX` | a name | none; `{prefix}` renders empty |
| `DOSSIER_MLFLOW_RUN_LABEL` | a name | none; `--label` wins over it (R10.11) |
| `DOSSIER_MLFLOW_USER` | a name | the account the command ran under (R10.12) |

The tracking URI has no default in code, for the reason the project's default
model has none (spec 009): a default is a value written into `.env.example`,
where it can be read, not a fallback nobody sees.

MLflow's own variables -- `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME` -- are
not read. R9.11 reads only `DOSSIER_` variables, and a shell left over from
another project must not switch this one's tracking on.

## Where records go

An experiment should hold runs that are comparable with one another. A sync's
fetch counts, a run's traces and an eval's per-field accuracy are not, and
neither are two evals over different gold sets. So the experiment is rendered
from a template per command kind:

| Placeholder | Holds | Available to |
|---|---|---|
| `{pipeline}` | the pipeline name, `incident-audit` | every command |
| `{kind}` | `sync`, `convert`, `run`, `eval`, `calibrate` or `compare` | every command |
| `{gold}` | the gold directory's name: `gold/incidents` gives `incidents` | `eval`, `calibrate` and `compare`, the commands that read one |

The default lays one pipeline out as:

```
dossier-audit/incident-audit/sync      per-source counts
dossier-audit/incident-audit/convert   per-source counts
dossier-audit/incident-audit/run       one MLflow run per dossier run; traces live here
dossier-audit/incident-audit/eval      per-field metrics, gold set by name and hash
dossier-audit/incident-audit/calibrate one MLflow run per measurement; a trace per sample case (R11.5)
dossier-audit/incident-audit/compare   per-field deltas between two runs (R11.8)
```

A template with no placeholder -- `dossier-audit` -- puts everything in one
experiment, and every record is still tagged with its kind and pipeline (R10.3),
so that layout remains filterable. A `{gold}` in the shared template needs an
override for every other kind, because sync, convert and run read no gold set;
that is what the per-kind variables are for. A calibration is the fifth kind
(R11.5): it reads a gold set as an eval does, so `{gold}` renders for it, and
R10.5 refuses it before its first judge call when the server is unreachable, as
it refuses a run before its first model call.

## How a record is named

The experiment says which records are comparable; the name says which one this
is. A list of forty evals all called `eval of <run id>` is filterable and not
readable: the thing a person is looking for -- which model, which prompt, which
attempt -- is in the params, one click away from a list they have to open forty
times.

So the name is rendered from a template per command kind, exactly as the
experiment is (R10.2), from values the command already holds:

| Placeholder | Holds | Available to |
|---|---|---|
| `{prefix}` | `DOSSIER_MLFLOW_RUN_PREFIX` and a separator, or empty | every command |
| `{label}` | a separator and the label, or empty (R10.11) | every command |
| `{pipeline}` | the pipeline name, `incident-audit` | every command |
| `{kind}` | `sync`, `convert`, `run`, `eval`, `calibrate` or `compare` | every command |
| `{started}` | when the command started, `20260806T142203Z` | every command |
| `{run_id}` | the run recorded, or the run scored | `run`, `eval` |
| `{model}` | that run's pinned model identifier | `run`, `eval` |
| `{pipeline_hash}` | that run's pipeline hash, eight characters | `run`, `eval` |
| `{gold}` | the gold set's name, `incidents` | `eval`, `calibrate`, `compare` |
| `{gold_hash}` | the gold set hash, eight characters | `eval`, `calibrate`, `compare` |
| `{judge_model}` | the judge's model identifier | `calibrate` |
| `{a}`, `{b}` | the two run ids being compared | `compare` |

A hash renders as eight characters because a name is read by a person, and the
display convention is already eight everywhere else in these specs. The full 64
are in the params and the tags, where a comparison is made (R0.7).

The defaults:

| Kind | Template | Renders |
|---|---|---|
| `sync` | `{prefix}sync {started}{label}` | `sync 20260806T142203Z` |
| `convert` | `{prefix}convert {started}{label}` | `convert 20260806T142203Z` |
| `run` | `{prefix}{run_id}{label}` | `20260806T142203Z-4f1a` |
| `eval` | `{prefix}eval {run_id} · {model}{label}` | `eval 20260806T142203Z-4f1a · anthropic:claude-sonnet-4-5-20250929` |
| `compare` | `{prefix}compare {a} -> {b}{label}` | `compare 20260806T142203Z-4f1a -> 20260907T090000Z-bbbb` |
| `calibrate` | `{prefix}calibrate {gold} · {judge_model}{label}` | `calibrate incidents · anthropic:claude-sonnet-4-5-20250929` |

Nothing is abbreviated. A model identifier is written as `model:` pins it and as
every param records it, because a shortened one is a second spelling of a value
whose whole point is to be exact (R0.6), and a reader who cannot map the name
back to the pin has to open the run anyway.

`{prefix}` and `{label}` carry their own separators, so a name with neither set
has no stray ` · ` at its edges -- which is what lets the defaults above leave
every name recorded before this spec byte-identical until someone configures one.

## What dossier writes about itself

Four tags under MLflow's own prefix, and no others: `mlflow.note.content`, the
description a person reads first (R11.12); `mlflow.user`, who ran it;
`mlflow.source.name` and `mlflow.source.type`, what ran it.

They are here because MLflow does **not** fill them on the path dossier records
through. `mlflow.start_run` -- the fluent API -- sets the user, the source name
and the source type from the process. `MlflowClient.create_run` does not: it
reads `mlflow.user` out of the tags it was handed and defaults it to `unknown`,
and it sets no source at all. dossier holds its run by id rather than activating
one, precisely so that a record is never an ambient global (R10.4), and the cost
is that Created by, Source and Description are blank on every record dossier has
ever written.

R10.3 said these were "left as MLflow sets them". On this path MLflow sets none
of them, so the rule was true only in the sense that nothing was there. R10.12
replaces it and names the four.

## The shape of a trace

One trace per (step, document) -- the unit of a cache key, so one trace is one
key computed or served (spec 011):

```
MLflow run 20260806T142203Z-4f1a
  trace  verify · INC-4821
    stage verify            cache miss · key 9f21c0a4
      llm  gemini:gemini-3.5-flash-lite   attempt 1
  trace  report · *
```

Spans are created explicitly rather than by `mlflow.openai.autolog`. The model
client is `dossier`'s own, over httpx (R9.2), so autolog has nothing to hook;
and R10.7 and R10.8 need control over exactly what a span holds.

## Where the code sits

The decisions -- reading the switch, rendering a template, choosing what a span
holds -- are pure, and live in `dossier.domain.tracking`. `application/` records
through a `Tracker` port in `domain/ports.py` and never imports MLflow; the test
suite hands it a `FakeTracker` that counts runs, traces and spans, as
`FakeModelClient` counts calls. Only `dossier.infrastructure.tracking` imports
`mlflow`, which makes it the third package permitted to reach the network (R0.10).

## Must hold

### R10.1 — tracking is off unless `DOSSIER_MLFLOW_ENABLED` is `true`

A value that is neither `true` nor `false` is refused rather than read as off:
a typo that silently disabled tracking would be found only after the run it
should have recorded.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.settings`)
- **Proved by:** `tests/unit/test_R010_1__tracking_is_off_unless_enabled.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_ENABLED=true`, `DOSSIER_MLFLOW_TRACKING_URI=http://localhost:5000` | on, recording to `http://localhost:5000` |
| 2 | neither variable set | off; 0 tracking calls |
| 3 | `DOSSIER_MLFLOW_ENABLED=ture` | refused before any work, naming the variable and the two values it takes |
| 4 | `DOSSIER_MLFLOW_ENABLED=true`, no URI | refused before any work, naming `DOSSIER_MLFLOW_TRACKING_URI` |
| 5 | *counter-example* — `MLFLOW_TRACKING_URI` set in the shell, `DOSSIER_MLFLOW_ENABLED` unset | off; MLflow's own variables do not switch dossier's tracking on |

### R10.2 — the experiment a record lands in is rendered from the template for its command

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.experiment_name`)
- **Proved by:** `tests/unit/test_R010_2__experiment_names_come_from_a_template.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | no template set, `dossier run incident-audit` | `dossier-audit/incident-audit/run` |
| 2 | `DOSSIER_MLFLOW_EXPERIMENT_EVAL=dossier-audit/{pipeline}/eval/{gold}`, `dossier eval incident-audit --gold gold/incidents` | `dossier-audit/incident-audit/eval/incidents`; the command's own template wins over `DOSSIER_MLFLOW_EXPERIMENT` |
| 3 | `DOSSIER_MLFLOW_EXPERIMENT=dossier-audit` | every command records to `dossier-audit`; a template with no placeholder is one experiment |
| 4 | `DOSSIER_MLFLOW_EXPERIMENT=dossier-audit/{source}` | refused before any work, naming the variable and the placeholders it may use: `{pipeline}`, `{kind}`, `{gold}` |
| 5 | *counter-example* — `{gold}` in the template `dossier sync` uses | refused; a sync reads no gold set |

### R10.3 — every record carries `dossier.kind` and `dossier.pipeline`, whichever experiment it lands in

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.tags`)
- **Proved by:** `tests/unit/test_R010_3__every_record_is_tagged_with_its_kind_and_pipeline.py`
- **Status:** SUPERSEDED by R10.12

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` | tags `dossier.kind=run`, `dossier.pipeline=incident-audit` |
| 2 | `DOSSIER_MLFLOW_EXPERIMENT=dossier-audit`, one run and one eval recorded | both in `dossier-audit`, told apart by `dossier.kind` |
| 3 | *counter-example* — `mlflow.user`, `mlflow.source.name` | left as MLflow sets them; dossier writes only under `dossier.` |

### R10.4 — enabling tracking changes no manifest, cache key, artifact or provenance record

Tracking observes a run; it is not an input to one (R0.5).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R010_4__tracking_changes_no_output.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the same inputs run with tracking on and with it off | byte-identical manifests apart from run id and start time (R0.4), and identical stage keys |
| 2 | a run recorded to MLflow | no file under `runs/20260806T142203Z-4f1a/` or `.dossier/` holds the MLflow run id |
| 3 | *counter-example* — what the command prints | one extra line naming the MLflow run; what a person reads may differ, what is written to disk may not |

### R10.5 — with tracking enabled, an unreachable server refuses the command before any work

Checked once, at startup. An hour of model calls nobody can inspect afterwards is
the failure this prevents.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R010_5__an_unreachable_server_refuses_before_any_work.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | tracking enabled, nothing answering at `http://localhost:5000`, `dossier run incident-audit` | exit 2 naming the URI; 0 model calls, no run directory |
| 2 | the same for `dossier sync incident-audit` | exit 2; 0 fetches, ledger unchanged |
| 3 | tracking enabled, the `tracking` extra not installed | exit 2 naming `dossier[tracking]` |
| 4 | *counter-example* — `dossier run incident-audit --plan` with the server down | proceeds; `--plan` records nothing, so it needs no server (R11.1) |
| 5 | the same for `dossier calibrate incident-audit --gold gold/incidents` | exit 2 naming the URI; 0 judge calls, no calibration file. Twenty model calls nobody can inspect afterwards is exactly the failure this rule prevents (R11.5) |

### R10.6 — a record lost after the startup check never changes a command's outcome

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.best_effort`)
- **Proved by:** `tests/unit/test_R010_6__a_lost_record_is_counted_and_swallowed.py`, `tests/acceptance/test_R010_6__a_lost_record_never_changes_the_outcome.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the server stops answering after the second of four traces | the run completes, 4 artifacts cached, `warning: 2 trace(s) could not be recorded`, exit 0 |
| 2 | the same, and `INC-4821` failed validation | exit 1, as without tracking (R6.9); a lost record neither raises it nor masks it |
| 3 | *counter-example* — the server down before the command starts | not this rule; refused by R10.5 |

### R10.7 — no credential's value reaches a tracking record

R9.8's promise, for MLflow.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R010_7__no_credential_reaches_a_tracking_record.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_GEMINI_API_KEY` set, a run recorded with `DOSSIER_MLFLOW_CAPTURE=full` | no param, tag, span input, output or attribute holds its value |
| 2 | OpenWebUI answering 401 at `http://localhost:8080/api` | the LLM span names the URL and the status, not the key (R9.8 row 1) |
| 3 | *counter-example* — "`DOSSIER_GEMINI_API_KEY` is not set" on a span | allowed; naming a variable is not disclosing it |

### R10.8 — `DOSSIER_MLFLOW_CAPTURE` decides whether a span carries document text or only its hashes

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.span_payload`)
- **Proved by:** `tests/unit/test_R010_8__capture_decides_text_or_hashes.py`, `tests/acceptance/test_R010_8__capture_decides_what_a_span_holds.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | unset | `full`: the verify span for `INC-4821` holds the rendered prompt and the model's reply |
| 2 | `DOSSIER_MLFLOW_CAPTURE=hashes` | the same span holds prompt `0e52dd18`, inputs `a3f9c1e2` and `77c1b40a`, key `9f21c0a4`, and no text |
| 3 | `DOSSIER_MLFLOW_CAPTURE=none` | refused before any work, naming the variable and `full`, `hashes` |
| 4 | *counter-example* — step, document key, model identifier, attempt count, field names, verdicts | recorded under both values; they identify, they do not disclose |

### R10.9 — the tracker points MLflow at the configured server before it records anything

`DOSSIER_MLFLOW_TRACKING_URI` names one server, and everything dossier records
goes there: runs, params, metrics, artifacts *and* traces.

That needs saying because MLflow has two paths. A run is written through the
`MlflowClient` dossier constructs with the URI; a trace is exported by MLflow's
own asynchronous exporter, which reads the library's process-wide configuration
rather than that client. Left unset, the exporter posts to MLflow's default local
store, where the experiment ids dossier just created on the server do not exist,
and every trace is dropped with a warning while the run itself records perfectly.
That silently empties R11.1 and R11.2 -- the run carries no traces, so no span
exists to count against a model call.

The fix is not to read `MLFLOW_TRACKING_URI`. R10.1 is deliberate: a variable
left in a shell from another project must switch nothing on and must not
redirect a record. The tracker configures the library it is using, from the value
dossier was given.

Configuring MLflow is not an input to a run: it changes where records land and
nothing about what the run computes (R10.4).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.mlflow`)
- **Proved by:** `tests/unit/test_R010_9__the_tracker_points_mlflow_at_the_configured_server.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a tracker built for `http://localhost:5000` | MLflow's tracking URI is set to `http://localhost:5000` before the first record |
| 2 | `MLFLOW_TRACKING_URI` set to another server in the shell | the tracker still records to the URI dossier was configured with; MLflow's own variable decides nothing (R10.1 row 5) |
| 3 | a run recorded against a live server | its traces are readable on the same server as its metrics, under the experiment the run was created in (R11.1) |
| 4 | *counter-example* — tracking off | no tracker is built, nothing is configured, and MLflow's own configuration is left exactly as it was |

### R10.10 — a record's name is rendered from the name template for its command

The same mechanism as R10.2, on the other thing a person reads in a list of runs.
`DOSSIER_MLFLOW_RUN_NAME_<KIND>` wins over the default for that kind; a template
naming a placeholder the command cannot fill is refused before any work, naming
the variable it came from, because a literal `{gold}` in a run's name is a name
nobody meant and records pile up under it unnoticed.

Every placeholder is a value the command already holds. Nothing is computed for
the name, and nothing is abbreviated to fit it.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.run_name`)
- **Proved by:** `tests/unit/test_R010_10__a_name_is_rendered_from_its_template.py`, `tests/acceptance/test_R010_10__a_record_is_named_from_its_template.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier eval incident-audit --gold gold/incidents`, nothing configured | `eval 20260806T142203Z-4f1a · anthropic:claude-sonnet-4-5-20250929` |
| 2 | `DOSSIER_MLFLOW_RUN_PREFIX=nightly`, the same | `nightly · eval 20260806T142203Z-4f1a · anthropic:claude-sonnet-4-5-20250929`; the prefix carries its own separator |
| 3 | `DOSSIER_MLFLOW_RUN_NAME_COMPARE={a} vs {b}` | `20260806T142203Z-4f1a vs 20260907T090000Z-bbbb`; a template with no `{prefix}` takes none |
| 4 | `DOSSIER_MLFLOW_RUN_NAME_RUN={gold} {run_id}` | refused before any work, naming the variable and the placeholders a run may use (R10.2's shape) |
| 5 | `DOSSIER_MLFLOW_RUN_NAME_EVAL={prefix}eval {gold_hash}` | `eval 3b7e1d90`; a hash in a name is its eight-character display form, not its 64 (R0.7) |
| 6 | *counter-example* — `dossier run incident-audit`, nothing configured | `20260806T142203Z-4f1a`, byte-identical to R11.1 row 1. Every name recorded before this rule is unchanged until someone configures one |

### R10.11 — the label a command is given is rendered into its name and tagged on its record

A version a person means -- `v2`, `after the prompt rewrite`, `nightly` -- is not
a figure dossier can derive. A count of the runs already on the server would be
one: it would name the same eval differently on another machine, and differently
again after a record was lost (R10.6). So the label is supplied, and the versions
dossier *can* defend -- the pipeline hash and the gold set hash -- are recorded
beside it (R11.11).

In the name so a list reads, and as a tag so a list filters. One value, two
places, one decision.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.tags`)
- **Proved by:** `tests/unit/test_R010_11__a_label_is_resolved_and_carried.py`, `tests/acceptance/test_R010_11__a_label_is_in_the_name_and_on_the_record.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier eval incident-audit --gold gold/incidents --label v2` | named `eval 20260806T142203Z-4f1a · anthropic:claude-sonnet-4-5-20250929 · v2`; tag `dossier.label=v2` |
| 2 | `DOSSIER_MLFLOW_RUN_LABEL=nightly` and `--label v2` | `v2`; the flag wins over the variable, as an argument wins over a default everywhere else |
| 3 | `dossier run incident-audit --label v2` | the same two places: every command that opens a record takes one |
| 4 | *counter-example* — no flag and no variable | no `dossier.label` tag at all, and a name with no trailing separator. Absent means nobody labelled it -- unlike `dossier.regressed`, which the command computes for every comparison and is therefore present and empty (R11.9 row 3) |

### R10.12 — dossier writes four `mlflow.*` tags, and no others

Supersedes R10.3, whose counter-example said `mlflow.user` and
`mlflow.source.name` were "left as MLflow sets them". `MlflowClient.create_run`
sets neither -- it reads `mlflow.user` from the tags handed to it and defaults it
to `unknown` -- so on dossier's path they were left empty rather than left alone,
and Created by, Source and Description have been blank on every record.

The four are `mlflow.note.content`, `mlflow.user`, `mlflow.source.name` and
`mlflow.source.type`. Everything dossier says about the *work* stays under
`dossier.`, which is what R10.3 was protecting and what this rule keeps.

`mlflow.user` is read where every per-machine value is read (R9.11): the account
the command ran under, overridden by `DOSSIER_MLFLOW_USER`. It is a name, not a
credential, and R10.7 is unaffected -- no value of a `_TOKEN` or `_API_KEY`
variable reaches a record.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.tags`)
- **Proved by:** `tests/unit/test_R010_12__dossier_writes_four_mlflow_tags_and_no_others.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` | `dossier.kind=run`, `dossier.pipeline=incident-audit` -- R10.3's rows 1 and 2, unchanged -- and `mlflow.source.name=dossier run`, `mlflow.source.type=LOCAL` |
| 2 | `DOSSIER_MLFLOW_USER=a.aleks` | `mlflow.user=a.aleks`; MLflow's UI shows it as Created by |
| 3 | `DOSSIER_MLFLOW_USER` unset | the account the command ran under; a machine with no such value records `unknown`, which is what MLflow would have stored anyway |
| 4 | a `dossier eval` with a description (R11.12) | `mlflow.note.content` holds it, and the Description box is no longer empty |
| 5 | *counter-example* — `mlflow.runName`, `mlflow.parentRunId`, `mlflow.log-model.history` | not written. The name goes through `run_name` (R10.10), and the other two are MLflow's own bookkeeping about a shape dossier does not use |
| 6 | *counter-example* — `DOSSIER_JIRA_TOKEN` set | its value is in no tag, `mlflow.` prefixed or otherwise (R10.7) |
