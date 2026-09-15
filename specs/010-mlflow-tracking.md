# 010 — MLflow tracking: the switch, where records go, and what tracking may not do

**Status:** Proposed
**Rules:** R10.1 – R10.8

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
| `DOSSIER_MLFLOW_EXPERIMENT_SYNC`, `_CONVERT`, `_RUN`, `_EVAL` | a template | falls back to `DOSSIER_MLFLOW_EXPERIMENT` |
| `DOSSIER_MLFLOW_CAPTURE` | `full` / `hashes` | `full` |

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
| `{kind}` | `sync`, `convert`, `run` or `eval` | every command |
| `{gold}` | the gold directory's name: `gold/incidents` gives `incidents` | `eval` only |

The default lays one pipeline out as:

```
dossier-audit/incident-audit/sync      per-source counts
dossier-audit/incident-audit/convert   per-source counts
dossier-audit/incident-audit/run       one MLflow run per dossier run; traces live here
dossier-audit/incident-audit/eval      per-field metrics, gold set by name and hash
```

A template with no placeholder -- `dossier-audit` -- puts everything in one
experiment, and every record is still tagged with its kind and pipeline (R10.3),
so that layout remains filterable. A `{gold}` in the shared template needs an
override for every other kind, because sync, convert and run read no gold set;
that is what the per-kind variables are for.

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
- **Status:** NOT MET

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
- **Status:** NOT MET

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
- **Status:** NOT MET

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
- **Status:** NOT MET

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
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | tracking enabled, nothing answering at `http://localhost:5000`, `dossier run incident-audit` | exit 2 naming the URI; 0 model calls, no run directory |
| 2 | the same for `dossier sync incident-audit` | exit 2; 0 fetches, ledger unchanged |
| 3 | tracking enabled, the `tracking` extra not installed | exit 2 naming `dossier[tracking]` |
| 4 | *counter-example* — `dossier run incident-audit --plan` with the server down | proceeds; `--plan` records nothing, so it needs no server (R11.1) |

### R10.6 — a record lost after the startup check never changes a command's outcome

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R010_6__a_lost_record_never_changes_the_outcome.py`
- **Status:** NOT MET

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
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_GEMINI_API_KEY` set, a run recorded with `DOSSIER_MLFLOW_CAPTURE=full` | no param, tag, span input, output or attribute holds its value |
| 2 | OpenWebUI answering 401 at `http://localhost:8080/api` | the LLM span names the URL and the status, not the key (R9.8 row 1) |
| 3 | *counter-example* — "`DOSSIER_GEMINI_API_KEY` is not set" on a span | allowed; naming a variable is not disclosing it |

### R10.8 — `DOSSIER_MLFLOW_CAPTURE` decides whether a span carries document text or only its hashes

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.span_payload`)
- **Proved by:** `tests/unit/test_R010_8__capture_decides_text_or_hashes.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | unset | `full`: the verify span for `INC-4821` holds the rendered prompt and the model's reply |
| 2 | `DOSSIER_MLFLOW_CAPTURE=hashes` | the same span holds prompt `0e52dd18`, inputs `a3f9c1e2` and `77c1b40a`, key `9f21c0a4`, and no text |
| 3 | `DOSSIER_MLFLOW_CAPTURE=none` | refused before any work, naming the variable and `full`, `hashes` |
| 4 | *counter-example* — step, document key, model identifier, attempt count, field names, verdicts | recorded under both values; they identify, they do not disclose |
