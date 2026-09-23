# 010 — MLflow tracking: the switch, where records go, and what tracking may not do

**Status:** Partially implemented
**Rules:** R10.1 – R10.23

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
| `DOSSIER_MLFLOW_NAMESPACE` | a name | none; every prompt and dataset name is exactly what R14.1, R14.2 and R12.1 compose (R10.13) |
| `DOSSIER_MLFLOW_RUN_LABEL` | a name | none; `--label` wins over it (R10.11) |
| `DOSSIER_MLFLOW_USER` | a name | the account the command ran under (R10.12) |
| `DOSSIER_MLFLOW_AUTH` | `none` / `basic` / `bearer` / `oidc` | `none`: no credential is sent (R10.16) |
| `DOSSIER_MLFLOW_AUTH_USERNAME`, `DOSSIER_MLFLOW_AUTH_PASSWORD` | the pair `basic` sends | none |
| `DOSSIER_MLFLOW_AUTH_TOKEN` | the token `bearer` sends | none |
| `DOSSIER_MLFLOW_OIDC_TOKEN_URL`, `_CLIENT_ID`, `_CLIENT_SECRET` | the client `oidc` exchanges for a token | none |
| `DOSSIER_MLFLOW_OIDC_SCOPE`, `DOSSIER_MLFLOW_OIDC_AUDIENCE` | sent with the exchange when set | not sent |
| `DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS` | a whole number of seconds | `30` (R10.19) |
| `DOSSIER_MLFLOW_CA_BUNDLE` | a PEM file | the system's trust store (R10.20) |

The tracking URI has no default in code, for the reason the project's default
model has none (spec 009): a default is a value written into `.env.example`,
where it can be read, not a fallback nobody sees.

MLflow's own variables -- `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME` -- are
not read. R9.11 reads only `DOSSIER_` variables, and a shell left over from
another project must not switch this one's tracking on.

`DOSSIER_MLFLOW_USER` is who a record says ran it (R10.12), and it is not a
login. The account dossier authenticates as is `DOSSIER_MLFLOW_AUTH_USERNAME`,
and the two are separate on purpose: a person's name on a record and the service
account a pipeline writes through are different facts, and one variable holding
both would send a display name as a credential.

## Authentication

A tracking server that anyone on a network can write to is the exception rather
than the rule. MLflow's own basic auth, a bearer token issued by a gateway, and a
server behind an OIDC identity provider such as Keycloak are all common setups, and
until R10.16 dossier could reach none of them. It sent no credential. A credential
exported in the shell as `MLFLOW_TRACKING_TOKEN` did reach MLflow, but only because
the library reads it for itself. That is the same accident R10.9 exists to
prevent, one variable further along.

`DOSSIER_MLFLOW_AUTH` names the mode. It is chosen, not inferred from which
variables happen to be set, for the reason `DOSSIER_MLFLOW_ENABLED` refuses a
typo (R10.1): a guess that picked the wrong mode would be found only after the
run it should have recorded.

| Mode | Sends | Suits |
|---|---|---|
| `none` | no `Authorization` header | a server on `localhost`, or one nothing guards |
| `basic` | `Basic` over the username and password | MLflow's own `--app-name basic-auth` |
| `bearer` | `Bearer` and the token as given | a personal access token, a gateway's API token, a long-lived JWT |
| `oidc` | `Bearer` and an access token exchanged for the client's credentials | Keycloak, Entra ID, Okta or Auth0 in front of MLflow, whether a proxy checks the token or MLflow does |

`oidc` is the OAuth 2.0 client-credentials grant: a service account, not a
person, which is the principal an unattended pipeline should run as. Its token
expires, typically in five minutes, and a `dossier run` over a real corpus does not
finish in five minutes. A static token pasted into `bearer` would record the
first documents and be refused for every record after it. R10.19 is the rule that
closes this.

MLflow resolves a credential per request, and it asks registered *request auth
providers* for one. `dossier` registers one, named `dossier`, through the
`mlflow.request_auth_provider` entry point, and names it in the process
environment as `MLFLOW_TRACKING_AUTH=dossier`. It is the one path every request
takes: a run's records, the traces MLflow's asynchronous exporter sends from a
thread of its own, and the dataset, model and prompt registries (R10.17). It is
the same function dossier's own startup check takes its header from. The header
checked at startup is therefore the header every later request sends, because
both come from one function.

The provider is also why no secret is written to the process environment. The
only values written there are the provider's name and, when
`DOSSIER_MLFLOW_CA_BUNDLE` is set, its path as `MLFLOW_TRACKING_SERVER_CERT_PATH`.
Neither is a secret. Both are written by `dossier.infrastructure.tracking`, and
only when tracking is on. `dossier.config` still reads the environment and never
writes it (R9.11).

The token exchange reads a response, which a package that "only sends" (R0.10)
might seem to forbid. It does not. The token is held inside
`dossier.infrastructure.tracking` and handed to nothing outside it. The `Tracker`
port still declares no method that returns anything read from a server, so no key,
manifest or score can depend on it.

What this does not cover, deliberately and for now:

- **A person logging in interactively** through a device-code or browser flow. A
  service account is what an unattended pipeline should run as, and a person
  can mint a token and use `bearer`.
- **A credential in a header other than `Authorization`**, such as Cloudflare
  Access's pair or an `X-API-Key` gateway.
- **The client secret sent as HTTP Basic** at the token endpoint. `oidc` sends it
  in the form body (`client_secret_post`), which Keycloak, Entra ID and Auth0
  accept by default and an Okta client can be set to.
- **Client certificates (mTLS)**, and **AWS SigV4**. MLflow's
  `MLFLOW_TRACKING_AWS_SIGV4` overrides a request auth provider, so a shell that
  sets it is outside what R10.17 can promise.
- **An artifact root that is not the tracking server.** An `s3://` or `gs://`
  root is authenticated by that store, not by MLflow. `changes.json` (R11.6) and
  every other artifact go there directly.

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
- **Proved by:** `tests/unit/test_R010_12__dossier_writes_four_mlflow_tags_and_no_others.py`, `tests/acceptance/test_R010_12__a_record_says_who_ran_it_and_what_ran_it.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit` | `dossier.kind=run`, `dossier.pipeline=incident-audit` -- R10.3's rows 1 and 2, unchanged -- and `mlflow.source.name=dossier run`, `mlflow.source.type=LOCAL` |
| 2 | `DOSSIER_MLFLOW_USER=a.aleks` | `mlflow.user=a.aleks`; MLflow's UI shows it as Created by |
| 3 | `DOSSIER_MLFLOW_USER` unset | the account the command ran under; a machine with no such value records `unknown`, which is what MLflow would have stored anyway |
| 4 | a `dossier eval` with a description (R11.12) | `mlflow.note.content` holds it, and the Description box is no longer empty |
| 5 | *counter-example* — `mlflow.runName`, `mlflow.parentRunId`, `mlflow.log-model.history` | not written. The name goes through `run_name` (R10.10), and the other two are MLflow's own bookkeeping about a shape dossier does not use |
| 6 | *counter-example* — `DOSSIER_JIRA_TOKEN` set | its value is in no tag, `mlflow.` prefixed or otherwise (R10.7) |

### R10.13 — a configured `DOSSIER_MLFLOW_NAMESPACE` goes in front of every name dossier publishes into MLflow's global namespace, and an unset one changes none

Two kinds of name `dossier` publishes are global on a server: a prompt's (R14.1,
R14.2) and a gold set's dataset's (R12.1). Each is unique within one workspace and
no further, so two checkouts sharing a server publish into one history -- which was
found live for prompts, when one checkout's publish arrived as `v2` of another's
(R14.8), and holds for datasets in a worse form: two workspaces each holding
`gold/incidents` merge their records into one dataset, keyed by document keys they
may share, and the stale check on each eval (R11.7) flips with whichever published
last.

One namespace per machine for both, rather than one variable per kind: what a
person means is "keep this checkout's records apart", and two variables are two
chances to set one and forget the other, which is the silent merge again. Read
with the rest of the tracking settings and never from committed files, because
which namespace a checkout publishes into is a fact about where it runs (R10.1).
Applied to every name a publish sends and every name a command looks up, so the
two can only agree.

Nothing else is namespaced. An experiment is named by a template this machine
already controls (R10.2), and a pipeline version is found by its content rather
than its name (R13.1), so two machines running the same pipeline share a version
because it *is* the same version.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.namespaced`)
- **Proved by:** `tests/acceptance/test_R010_13__a_namespace_goes_in_front_of_every_published_name.py`, `tests/unit/test_R010_13__a_namespace_goes_in_front_of_a_name.py`, `tests/unit/test_R010_13__a_gold_set_publishes_under_the_namespace.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_NAMESPACE=sandbox`, `dossier prompts publish incident-audit` | `sandbox.incident-audit.extract`, `sandbox.incident-audit.verify`, `sandbox.incident-audit.report` and `sandbox.incident-audit.judge.root_cause`, each at version 1 |
| 2 | the same namespace, `dossier dataset publish incident-audit --gold gold/incidents` | 1 dataset `sandbox.incidents`, 4 records, in `dossier-audit/incident-audit/eval/incidents` |
| 3 | two workspaces each holding `gold/incidents`, one publishing with `sandbox` and one with no namespace | two datasets, `sandbox.incidents` and `incidents`, 4 records each. Without the namespace the second publish would have merged its records onto the first's, which is the failure this rule exists for |
| 4 | published under `sandbox`, then `dossier eval incident-audit --gold gold/incidents` and `dossier run incident-audit` on the same machine | the eval links dataset `sandbox.incidents` (R11.7) and rubric `sandbox.incident-audit.judge.root_cause` (R14.9); the run links `sandbox.incident-audit.extract` (R14.7). Every lookup is under the name a publish would have sent |
| 5 | *counter-example* — unset, or set to the empty string | every name byte-identical to what R14.1, R14.2 and R12.1 compose: `incident-audit.extract`, `incidents`. A prompt or dataset published before this rule is found, compared and not sent again (R14.4, R12.3) |
| 6 | *counter-example* — the experiment a namespaced dataset is published into | `dossier-audit/incident-audit/eval/incidents`, unchanged: `{gold}` renders the gold directory, not the namespaced dataset, and an experiment's name is already this machine's to template (R10.2) |

### R10.14 — a `DOSSIER_MLFLOW_NAMESPACE` MLflow would reject is refused before any work by every command that records, and by none while tracking is off

R14.10's rule, for the variable that replaced R14.8's. A namespace goes in front of
every prompt name, and MLflow rejects `/` and `:` in one, so a namespace holding
either can name nothing a publish would send. It is refused where the rest of this
machine's tracking settings are refused: before anything is fetched, asked or
recorded, with exit 2 naming the variable (R10.1, R10.5).

A dataset name would take either character -- a live spike on 2026-09-23 created
and found `team/a.incidents`, `team:a.incidents` and `a b.incidents` -- and the
namespace is refused for `dataset publish` all the same. It is one namespace in
front of every published name, and the name it cannot go in front of decides.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main._tracking_for`), over `dossier.domain.tracking.check_namespace`
- **Proved by:** `tests/acceptance/test_R010_14__a_namespace_mlflow_would_reject_is_refused_before_any_work.py`, `tests/unit/test_R010_14__a_namespace_mlflow_would_reject_is_refused_by_name.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_NAMESPACE=team/a`, tracking on, `dossier eval incident-audit --gold gold/incidents` | exit 2 naming `/` and `DOSSIER_MLFLOW_NAMESPACE`; 0 judge calls and 0 MLflow runs opened |
| 2 | the same namespace, `dossier calibrate incident-audit --gold gold/incidents` | exit 2 naming the variable; 0 judge calls and 0 MLflow runs opened |
| 3 | the same namespace, `dossier run incident-audit` | exit 2 naming the variable; 0 model calls and 0 MLflow runs opened |
| 4 | the same namespace, `dossier sync incident-audit` | exit 2 naming the variable; 0 items fetched |
| 5 | the same namespace, `dossier dataset publish incident-audit --gold gold/incidents` | exit 2 naming the variable; 0 datasets created, although a dataset name alone could have held `/` |
| 6 | *counter-example* — `team/a`, `DOSSIER_MLFLOW_ENABLED=false`, `dossier run incident-audit` | exit 0, as the run would have. Nothing is recorded or looked up, so nothing reads the namespace |
| 7 | *counter-example* — `DOSSIER_MLFLOW_NAMESPACE=sandbox` | nothing refused; every command records as R10.13 row 1 names |

### R10.15 — `DOSSIER_MLFLOW_PROMPT_PREFIX`, set to a value, is refused by name before any work, naming `DOSSIER_MLFLOW_NAMESPACE`

The variable R14.8 read, retired by R10.13. Ignored rather than refused, a machine
that still sets it would stop being namespaced without a word, and its next publish
would land in the history it had been set to keep apart from -- the silent merge,
arrived at by an upgrade instead of by an omission. Refused, it names the one
change to make.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.namespace`)
- **Proved by:** `tests/acceptance/test_R010_15__the_retired_prompt_prefix_is_refused_by_name.py`, `tests/unit/test_R010_15__the_namespace_is_read_and_the_retired_variable_refused.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `.env` holding `DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox`, tracking on, `dossier prompts publish incident-audit` | exit 2 naming `DOSSIER_MLFLOW_PROMPT_PREFIX` and `DOSSIER_MLFLOW_NAMESPACE`; 0 prompts sent |
| 2 | the same, `dossier run incident-audit` | exit 2 naming both variables; 0 model calls and 0 MLflow runs opened |
| 3 | *counter-example* — `DOSSIER_MLFLOW_PROMPT_PREFIX=`, blank | not refused. Blank is not a decision, as a blank switch is not (R10.1): a `.env` copied from an old `.env.example` ships it that way |
| 4 | *counter-example* — `DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox`, `DOSSIER_MLFLOW_ENABLED=false`, `dossier run incident-audit` | exit 0. Nothing is published or looked up, so nothing reads it |

### R10.16 — `DOSSIER_MLFLOW_AUTH` decides which credential dossier sends, from that mode's variables alone

A mode missing a variable it needs is refused before any work, naming the
variable. An empty value counts as unset, as an empty endpoint does (R9.2):
`.env.example` ships its variables blank, and blank is not a decision.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.settings`)
- **Proved by:** `tests/unit/test_R010_16__the_auth_mode_decides_the_credential.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_AUTH` unset, or `none` | no credential |
| 2 | `DOSSIER_MLFLOW_AUTH=basic`, `DOSSIER_MLFLOW_AUTH_USERNAME=dossier-ci`, `DOSSIER_MLFLOW_AUTH_PASSWORD` set | `Basic` over `dossier-ci` and that password |
| 3 | `DOSSIER_MLFLOW_AUTH=bearer`, `DOSSIER_MLFLOW_AUTH_TOKEN` set | `Bearer` and that token, as given |
| 4 | `DOSSIER_MLFLOW_AUTH=oidc`, `DOSSIER_MLFLOW_OIDC_TOKEN_URL=https://sso.example.internal/realms/dossier/protocol/openid-connect/token`, `_CLIENT_ID=dossier-ci`, `_CLIENT_SECRET` set | `Bearer` and an access token exchanged at that URL (R10.19) |
| 5 | `DOSSIER_MLFLOW_AUTH=basic`, `DOSSIER_MLFLOW_AUTH_USERNAME=dossier-ci`, no password | refused before any work, naming `DOSSIER_MLFLOW_AUTH_PASSWORD` |
| 6 | `DOSSIER_MLFLOW_AUTH=oidc`, `DOSSIER_MLFLOW_OIDC_CLIENT_SECRET=` in `.env` | refused, naming `DOSSIER_MLFLOW_OIDC_CLIENT_SECRET`; set and empty is unset |
| 7 | `DOSSIER_MLFLOW_AUTH=keycloak` | refused before any work, naming the variable and the four values it takes: `none`, `basic`, `bearer`, `oidc` |
| 8 | *counter-example* — `DOSSIER_MLFLOW_AUTH_TOKEN` set, `DOSSIER_MLFLOW_AUTH` unset | no credential; a variable for a mode nobody chose chooses nothing |
| 9 | *counter-example* — `DOSSIER_MLFLOW_USER=a.aleks`, `DOSSIER_MLFLOW_AUTH=basic`, no `DOSSIER_MLFLOW_AUTH_USERNAME` | refused, naming `DOSSIER_MLFLOW_AUTH_USERNAME`; who a record says ran it (R10.12) is never a login |
| 10 | *counter-example* — `DOSSIER_MLFLOW_ENABLED` unset, `DOSSIER_MLFLOW_AUTH=keycloak` | off, and not refused; nothing reads a credential for a server nothing records to (R10.1) |

### R10.17 — every request dossier makes to MLflow carries the credential R10.16 decided, and no other

R10.9 said everything goes to one server, and this rule is the matching claim
about the credential. A run's records and a trace take different paths through
MLflow. If the credential reached only one of them, the run would record and its
traces would be refused. A credential MLflow finds for itself in the shell, or in
`~/.mlflow/credentials`, decides nothing: in mode `none` it is removed rather than
sent. It was set for some server, and nothing says that server is this one.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.auth`)
- **Proved by:** `tests/unit/test_R010_17__every_request_carries_the_configured_credential.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `basic` as `dossier-ci`, `dossier run incident-audit` | the startup check, `create_run`, every `log_batch` and every trace MLflow's exporter sends carry the same `Basic` header |
| 2 | `bearer`, `dossier prompts publish incident-audit` | the prompt registry's requests carry `Bearer` and the token; `dossier dataset publish` and a pipeline version's registration likewise |
| 3 | `MLFLOW_TRACKING_TOKEN` set in the shell, `DOSSIER_MLFLOW_AUTH=basic` | `Basic`; MLflow's own variable decides nothing (R10.9 row 2) |
| 4 | `MLFLOW_TRACKING_USERNAME` and `MLFLOW_TRACKING_PASSWORD` set in the shell, `DOSSIER_MLFLOW_AUTH` unset | no `Authorization` header on any request. A credential left in a shell for another server is not sent to this one |
| 5 | any mode, after startup | the process environment holds `MLFLOW_TRACKING_AUTH=dossier`, and the value of no `DOSSIER_MLFLOW_AUTH_*` or `DOSSIER_MLFLOW_OIDC_*` variable |
| 6 | a run recorded against a live `mlflow server --app-name basic-auth` | its traces are readable on that server beside its metrics (R10.9 row 3) |
| 7 | *counter-example* — tracking off | no provider is named, and `MLFLOW_TRACKING_AUTH` is left exactly as it was (R10.9 row 4) |
| 8 | dossier installed from metadata older than the provider's entry point, so MLflow cannot find it | refused before any work, saying to reinstall dossier. MLflow would send no credential while the startup check, which takes its header from dossier directly, passed |

### R10.18 — a server that refuses the credential refuses the command before any work

This extends R10.5. MLflow's own basic auth leaves `/health` unauthenticated, so a
check that asks only `/health` passes with a credential that every later record
will fail. The startup check therefore makes one read that needs the credential,
with the credential. A `401` or `403` is reported as a refused credential. A
redirect is reported with the location it points to: behind a proxy, that is an
identity provider's login page, which a command cannot follow. Neither is
reported as "no MLflow server answers here".

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R010_18__a_refused_credential_refuses_before_any_work.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `basic` as `dossier-ci` with the right password, `https://mlflow.example.internal` | `/health` and the read both answer 200; the command proceeds |
| 2 | the wrong password: `/health` answers 200, the read answers 401 | `dossier run incident-audit` exits 2 naming the URI, the 401, `DOSSIER_MLFLOW_AUTH_USERNAME` and `DOSSIER_MLFLOW_AUTH_PASSWORD`; 0 model calls, no run directory, and the password's value in no message |
| 3 | `DOSSIER_MLFLOW_AUTH` unset, the read answers 401 | exit 2, saying the server wants a credential and `DOSSIER_MLFLOW_AUTH` is not set |
| 4 | behind a proxy, either request answers 302 to `https://sso.example.internal/realms/dossier/protocol/openid-connect/auth` | exit 2 naming that location, as a credential the server did not accept; not "no MLflow server answers" |
| 5 | the same wrong password, `dossier dataset publish` or `dossier prompts publish` | the same exit and the same message; every command that connects makes the same check |
| 6 | *counter-example* — the read answers 200, and `dossier-ci` holds only READ on `dossier-audit/incident-audit/run` | the command proceeds. A read cannot prove write access; the first refused write is R10.22 |
| 7 | *counter-example* — `DOSSIER_MLFLOW_TRACKING_URI=sqlite:///mlflow.db` | no server, so no check, as under R10.5 |

### R10.19 — an OIDC access token is fetched before any work, and fetched again once no more than the refresh margin remains

The margin is `DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS`, 30 seconds unless set. The
decision is taken per request against a clock passed in as an argument, because a
`dossier run` keeps its client open for longer than any one token lives. The
exchange is the client-credentials grant, with the secret in the form body.

A refresh that fails after the startup check loses a record and not the run
(R10.6). The token never leaves `dossier.infrastructure.tracking`, and nothing
read from the token endpoint reaches a key, a manifest or a score (R0.10).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.token_due`)
- **Proved by:** `tests/unit/test_R010_19__an_oidc_token_is_fetched_again_before_it_expires.py`, `tests/acceptance/test_R010_19__a_token_endpoint_that_refuses_refuses_before_any_work.py`
- **Status:** IN PROGRESS

| # | Given | Then |
|---|-------|------|
| 1 | `oidc`, the token endpoint answering `expires_in: 300` at `2026-08-06T09:00:00Z` | 1 token request, before the startup check. The form holds `grant_type=client_credentials`, `client_id=dossier-ci`, `client_secret`, and nothing else |
| 2 | a record sent at `09:04:29Z` | the same token; 1 token request in total |
| 3 | a record sent at `09:04:30Z` | a new token first; 2 token requests. Exactly 30 seconds left is due, because the margin is *no more than*, and this row is the one that pins it |
| 4 | `DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS=60` | due from `09:04:00Z`; the margin is read, not hard-coded |
| 5 | `DOSSIER_MLFLOW_OIDC_SCOPE=mlflow`, `DOSSIER_MLFLOW_OIDC_AUDIENCE=https://mlflow.example.internal` | the form also holds `scope=mlflow` and that `audience` |
| 6 | the token endpoint answers 401 `invalid_client` | exit 2 before any work, naming the token URL, `DOSSIER_MLFLOW_OIDC_CLIENT_ID` and `DOSSIER_MLFLOW_OIDC_CLIENT_SECRET`; the secret's value in no message; 0 model calls |
| 7 | nothing answers at the token URL | exit 2, naming `DOSSIER_MLFLOW_OIDC_TOKEN_URL` |
| 8 | `DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS=soon`, or `-5` | refused before any work, naming the variable |
| 9 | an answer of `expires_in: 20`, or none at all, under the default margin | a new token for every request. A margin longer than a token's life costs a token request, never a record, and a token whose lifetime is unknown is not reused on a guess |
| 10 | *counter-example* — the token endpoint stops answering at `09:04:30Z`, mid-run | that record is lost and counted (R10.21); the run completes with the exit it would have had untracked (R10.6) |
| 11 | *counter-example* — `basic` or `bearer` | 0 token requests |

### R10.20 — `DOSSIER_MLFLOW_CA_BUNDLE`, when set, is what every request to MLflow and to its token endpoint is verified against

A server signed by a private CA is a common setup, and dossier has to trust that
CA on every connection it makes: the startup check, the token exchange, and
MLflow's own requests. A relative path is resolved against the working
directory, as `.env` is. No `DOSSIER_` variable turns verification off. A private
CA can be trusted, and verification is never skipped.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.mlflow`)
- **Proved by:** `tests/unit/test_R010_20__a_private_ca_is_trusted_on_every_request.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_CA_BUNDLE=certs/example-internal.pem`, `https://mlflow.example.internal` signed by that CA | the startup check, the token exchange and MLflow (through `MLFLOW_TRACKING_SERVER_CERT_PATH`) all verify against it; the command proceeds |
| 2 | unset, the same server | exit 2 naming the URI and the verification failure, and naming `DOSSIER_MLFLOW_CA_BUNDLE` as the setting that trusts a private CA |
| 3 | `DOSSIER_MLFLOW_CA_BUNDLE=certs/missing.pem` | refused before any work, naming the variable and the path |
| 4 | *counter-example* — `http://localhost:5000` | no TLS, and the bundle is not read |

### R10.21 — every command that records says how many of its records were lost

R10.6 counted lost traces, and only `dossier run` has traces. A sync whose records
were all lost printed a clean terminal and exited 0, and a person who then found
nothing in MLflow had nothing to go on. A lost record is still not a lost run
(R10.6). This rule only makes the loss visible.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.best_effort`)
- **Proved by:** `tests/unit/test_R010_21__every_lost_record_is_counted.py`, `tests/acceptance/test_R010_21__every_command_says_how_many_records_were_lost.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | the server stops answering after the startup check, `dossier sync incident-audit` | the sync completes and the ledger is updated as it would be untracked; `warning: 6 record(s) could not be recorded`; exit 0 |
| 2 | the same, `dossier run incident-audit` | the record count, and R10.6 row 1's trace count beside it |
| 3 | the same, `dossier convert`, `dossier eval`, `dossier eval --compare` or `dossier calibrate` | the same line |
| 4 | *counter-example* — nothing lost | no line at all; `0 record(s)` is not printed |
| 5 | *counter-example* — the server down before the command starts | not this rule; refused by R10.5 |

### R10.22 — the first record a server refuses is reported as it is refused

A 401 or a 403 is not a server going away. It is configuration a person can fix,
and on `dossier run` the report comes before the first model call. It is printed
once. Every refusal after it goes into R10.21's count, and none of them changes
the outcome (R10.6).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.best_effort`)
- **Proved by:** `tests/unit/test_R010_22__a_refused_record_is_reported_as_it_is_refused.py`, `tests/acceptance/test_R010_22__a_refused_write_is_reported_before_the_work.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier-ci` holds READ on `dossier-audit/incident-audit/run` (MLflow's `default_permission = READ`), `dossier run incident-audit` | `create_run` answers 403, and a warning naming the 403, the experiment and `DOSSIER_MLFLOW_AUTH_USERNAME` is printed before the first model call; the run completes; exit 0 |
| 2 | every record after it refused as well | the warning once, not once per record; R10.21's count says how many |
| 3 | the same account, `dossier sync incident-audit` | printed when the sync opens its record, which is after the work: a sync records what it did once it has done it (R11.4); exit 0 |
| 4 | *counter-example* — the server answers 503, or stops answering | no warning as it happens, only R10.21's count. A server that has gone away tells a person nothing they can fix from the terminal |
| 5 | *counter-example* — the warning, in any mode | holds no password, token or client secret's value (R10.7) |

### R10.23 — MLflow writes nothing to a command's terminal, and never before the record it is closing

What a command prints is dossier's (R10.4 row 3). `MlflowClient.set_terminated`
prints `🏃 View run … at: …` and `🧪 View experiment at: …` to standard output,
and it does so *before* sending the update that closes the run. Where standard
output cannot encode the emoji -- a Windows console redirected to a file or a
pipe, which is `cp1252` -- the print raises, the update is never sent, and
`BestEffortTracker` swallows the error as a lost record (R10.6). Every run
recorded that way stayed `RUNNING` for ever, and the command exited 0 on a clean
terminal. It was found during R10.17's live check, and it was on `main` before
any authentication existed.

MLflow's own `MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT` skips the print. The tracker
sets it through MLflow's API wherever it configures the library (R10.9, R10.17),
and only when tracking is on.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.mlflow`)
- **Proved by:** `tests/unit/test_R010_23__mlflow_writes_nothing_to_the_terminal.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync incident-audit` with standard output piped on Windows (`cp1252`) | the run closes `FINISHED`; the update is sent, and nothing is written before it |
| 2 | `dossier run incident-audit`, recorded | no `🏃 View run` or `🧪 View experiment` line on standard output |
| 3 | *counter-example* — `recorded to MLflow: dossier-audit/incident-audit/run · run 20260806T142203Z-4f1a` | printed. That line is dossier's own, from the figures it holds, not MLflow's (R10.4 row 3) |
| 4 | *counter-example* — tracking off | nothing configured; MLflow's setting is left as it was (R10.9 row 4) |
