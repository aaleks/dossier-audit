# 08 · Solution

Every command below was run against this repository, against a real MLflow 3.15
server. The output shown is the output it produced.

## Run the prepared answer

Terminal 1 — MLflow:

```bash
mkdir -p playground/work/08
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/08/mlflow.db \
  --default-artifact-root $PWD/playground/work/08/mlartifacts \
  --host 127.0.0.1 --port 5000
```

Terminal 2 — the stub model (exercise 07's rules):

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/07-calibrating-a-judge/resources/replies-judge.json \
  --replies playground/07-calibrating-a-judge/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 3 — build the workspace exactly as exercise 07's solution does, then add
to `.env`:

```
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5000
```

```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000   # see task 6 — needed for traces
cd playground/work/08
D=../../../.venv/bin/dossier
$D sync incident-audit && $D convert incident-audit && $D run incident-audit
$D calibrate incident-audit --gold gold/incidents
$D eval incident-audit --gold gold/incidents
```

---

## Task 1 — the switch, and two refusals

```console
$ dossier run incident-audit          # DOSSIER_MLFLOW_ENABLED=yes
incident-audit: DOSSIER_MLFLOW_ENABLED is 'yes'; it takes `true` or `false`.
exit 2

$ dossier run incident-audit          # URI pointing at nothing
incident-audit: tracking is enabled and no MLflow server answers at http://127.0.0.1:5999
([Errno 111] Connection refused). Start it, or set DOSSIER_MLFLOW_ENABLED=false.
exit 2
```

Both before any work. The health check is one `GET /health` at startup, and the
reason it is there rather than at the first record is in R10.5: an hour of model
calls nobody can inspect afterwards is the failure being prevented. Note the
message names the fix — including the way to proceed *without* tracking, which is
what you usually want at that moment.

`MLFLOW_TRACKING_URI` on its own switches nothing on. Only `DOSSIER_` variables
are read (R10.1, R9.11), so a variable left in a shell from another project cannot
start recording your audit somewhere you did not choose. (Task 6 is about the one
place that decision has a cost.)

## Task 2 — one experiment per command

```console
$ python -c "
from mlflow import MlflowClient
for e in MlflowClient(tracking_uri='http://127.0.0.1:5000').search_experiments(): print(e.experiment_id, e.name)"
5 dossier-audit/incident-audit/eval
4 dossier-audit/incident-audit/calibrate
3 dossier-audit/incident-audit/run
2 dossier-audit/incident-audit/convert
1 dossier-audit/incident-audit/sync
0 Default
```

The default template is `dossier-audit/{pipeline}/{kind}`. One experiment per
pipeline and command kind, because a sync's fetch counts, a run's traces and an
eval's per-field accuracy are not comparable with one another — they do not share
an experiment unless somebody asks them to.

Asking is `DOSSIER_MLFLOW_EXPERIMENT=dossier-audit`, and what keeps that usable is
that every record carries `dossier.kind` and `dossier.pipeline` as tags (R10.3),
whichever experiment it lands in. Written under dossier's own prefix only: what
MLflow records about a run — `mlflow.user`, `mlflow.source.name` — is left as
MLflow sets it.

```console
$ dossier run incident-audit     # DOSSIER_MLFLOW_EXPERIMENT=dossier/{pipeline}/{source}
incident-audit: DOSSIER_MLFLOW_EXPERIMENT is 'dossier/{pipeline}/{source}', which uses
{source}; a template may use only {pipeline}, {kind}, {gold}.
exit 2

$ dossier run incident-audit     # …/{gold}
incident-audit: DOSSIER_MLFLOW_EXPERIMENT is 'dossier/{pipeline}/{gold}', and `dossier run`
reads no gold set, so there is nothing to put in {gold}. Set DOSSIER_MLFLOW_EXPERIMENT_RUN
to a template without it.
exit 2
```

The second message is the better one: `{gold}` is perfectly valid for `eval` and
`calibrate`, and the fix is the per-command variable, which the message names.

## Task 3 — what each command records

```
sync       metrics: incidents-manual/known 0 · changed 0 · new 5 · fetched 5 · failed 0
convert    metrics: incidents-manual/held 5 · converted 5 · cached 0 · failed 0
run        params : pipeline, model, pipeline_hash
           metrics: documents 5 · cache_hits 0 · model_calls 5 · failed 0
           artifact: manifest.json
           traces : 5
calibrate  params : judge/root_cause/model, judge/root_cause/rubric
           metrics: judge/root_cause/agreement 100.0 · judge/root_cause/cases 20
           traces : 20
eval       params : model, gold, judge/root_cause/model, judge/root_cause/agreement
           metrics: accuracy/loss_amount … accuracy/root_cause, accuracy/overall
           traces : 4
```

**The counts are the same numbers, under the same names, as the terminal printed.**
`sync` printed `5 new -> 5 fetched`; MLflow holds `new 5` and `fetched 5`. That is
not a coincidence of implementation, it is spec 011: the figures are computed once,
by the command, and the recorder is *handed* them. MLflow is a second place to
read a figure, never a second way of arriving at one.

The history behind that rule is worth knowing. The report and the MLflow record
were briefly allowed to work a figure out separately, and they disagreed about a
judge that had never been measured: a metric recorded for a field the report had
already refused to print, with every check green.

Which is exactly what task 3's second question tests. With `root_cause` withheld
(a stale calibration):

```console
params : {'model': 'openai:gpt-5.4-mini', 'gold': 'incidents', …}
metrics: {'accuracy/loss_amount': 100.0, 'accuracy/resolution_date': 100.0,
          'accuracy/severity': 100.0, 'accuracy/affected_systems': 100.0,
          'accuracy/overall': 100.0}
tags   : {'dossier.kind': 'eval', 'dossier.pipeline': 'incident-audit',
          'dossier.run_id': '20260917T211008Z-901b',
          'dossier.gold_hash': '2e0c83619a3b36b2…',
          'dossier.judge.root_cause': 'calibration is stale: the rubric has changed since'}
```

No `accuracy/root_cause` metric at all — not a zero, not a null — and
`accuracy/overall` covers only the fields that were reported. The reason it was
withheld is recorded as a **tag**, so the run says why the metric is missing. A
metric there would be the number R7.15 just refused, in the place people build
dashboards from.

`dossier.gold_hash` is worth a moment too: it is the hash of the gold files' bytes
as they were read, so a score recorded in March can be checked against the
definition of correct that produced it.

## Task 4 — reading a trace

```console
$ python - <<'PY'
from mlflow import MlflowClient
c = MlflowClient(tracking_uri="http://127.0.0.1:5000")
exp = c.get_experiment_by_name("dossier-audit/incident-audit/run")
t = c.search_traces([exp.experiment_id], max_results=1)[0]
print({k: v for k, v in dict(t.info.tags).items() if k.startswith("dossier")})
for s in t.data.spans:
    print(" ", s.name, s.span_type, {k: v for k, v in (s.attributes or {}).items() if k.startswith("dossier")})
PY
{'dossier.step': 'extract', 'dossier.document': 'PLAY-1005.md'}
  extract · PLAY-1005.md UNKNOWN {}
  extract STAGE {'dossier.cache': 'miss', 'dossier.key': '5988a9bfdb9d46b2…'}
  openai:gpt-5.4-mini LLM {'dossier.model': 'openai:gpt-5.4-mini', 'dossier.attempt': 1}
```

One trace per (step, document), tagged with both (R11.1). Inside it, a stage span
saying which key this was and whether it was served, and one LLM span per model
call (R11.2) carrying the attempt number — so exercise 06's retry shows up here as
two LLM spans in one trace.

Run again with everything cached and the traces change shape:

```
  extract STAGE {'dossier.cache': 'hit', 'dossier.key': '5988a9bfdb9d46b2…'}
```

A stage span and **no LLM span at all**. The hit is recorded as carefully as the
miss, because seeing that a document cost nothing is information — and the key
tells you which stored answer served it, which is the thing you want when a
result surprises you.

`FakeModelClient`'s call count in the test suite and this span count are the same
claim seen twice (R11.2). If a run's `model_calls` metric and its LLM spans ever
disagree, one of them is lying.

With a document failing, the run's MLflow status is `FAILED`, and the failing
document's trace ends with an error — the record and the exit code agree.

## Task 5 — keep the documents off the server

```console
$ # DOSSIER_MLFLOW_CAPTURE=hashes
  openai:gpt-5.4-mini LLM
     dossier.model = openai:gpt-5.4-mini
     dossier.attempt = 1
     prompt_hash = b3c909cfe88ac27ee0ff7bd2f51cd7dc6961900e2607199bbfcf5186df57ba0a
     input_hashes = ['4a3401534177d21d521501e791c91f7ac1d97c932339c507d19f19eb660d2470']
     key = 5988a9bfdb9d46b2bf09f04b901421f87a0a88cb93e91f1a0261be55df9eb790
```

versus `full`:

```console
  openai:gpt-5.4-mini LLM
     dossier.model = openai:gpt-5.4-mini
     dossier.attempt = 1
     prompt = Extract the requested fields from the incident note below.…
     reply = {'document': 'PLAY-1005.md', 'fields': [{'confidence': 'high', …
```

Under `hashes` the span still says *exactly which question was asked* — the three
hashes are the same three the cache key is made of — and carries no document text
at all (R10.8). That is the setting for a confidential corpus on a shared server,
and the value is checked before any work for the same reason the switch is: read
as `full`, a typo would copy text you meant to keep out of the server, and finding
that out after the run is finding it out after the copy.

What did not change, across tracking on, off, `full` and `hashes`: the run id
format, the manifest, every artifact and every cache key. That is R10.4, and the
way to be sure is to check rather than to trust:

```bash
find .dossier/cache/stage -type f ! -name '*.meta.json' | sort | xargs cat | sha256sum
# flip the setting, clear the stage cache, run again
find .dossier/cache/stage -type f ! -name '*.meta.json' | sort | xargs cat | sha256sum
```

Same digest. Tracking observes a run; it is not an input to one.

## Task 6 — when traces do not arrive

On MLflow 3.15 the first tracked run produced this, five times:

```
WARNING mlflow.tracing.export.mlflow_v3: Failed to send trace to MLflow backend:
No Experiment with id=3 exists
```

Runs, params, metrics and the manifest artifact all arrived. Only the traces were
lost — and the run still succeeded, which is R10.6 working as designed: a record
lost after the startup check never changes a command's outcome.

**The cause, in one sentence:** `dossier` passes its tracking URI to
`MlflowClient`, but MLflow 3.x's asynchronous *trace* exporter resolves its
destination from the global MLflow configuration rather than from that client, so
with `MLFLOW_TRACKING_URI` unset it posts traces to the default local store —
where the experiment ids `dossier` created on the server do not exist.

**The workaround**, and it is what the setup block above does:

```bash
export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
```

Traces then land, and everything in task 4 is visible.

**Why this is not simply a bug in the configuration.** Not reading MLflow's own
variables is deliberate and is R10.1 — "a variable left in a shell from another
project switches nothing on" — so the fix cannot be "read `MLFLOW_TRACKING_URI`
too". The honest options are for `MlflowTracker` to set MLflow's global tracking
URI itself when it connects, or to export traces through a client-scoped path.
Either is a behaviour change, so in this repository it starts as a spec
conversation about R11.1: the rule claims a run records one trace per (step,
document), and on a current MLflow that claim is only true if something sets the
global URI. The test suite cannot see it, because the tracker's tests use a
`FakeTracker` and never reach MLflow.

That is the most transferable thing in this exercise. A rule with a green test can
still be false in production when the test replaces the very boundary the rule is
about. The way you find out is by running the real thing once and looking.

---

## What to take to your own project

- Switch observability on explicitly, from your own namespace, and refuse a typo
  rather than reading it as "off".
- Check the recorder before doing the work, not after.
- Compute a figure once and hand it to the recorder. Two places that compute the
  same number will eventually disagree, and the one on the dashboard is the one
  people will quote.
- Record misses *and* hits. "This cost nothing" is information.
- Give yourself a way to trace without shipping the documents.
- Exercise the real integration at least once. Fakes do not test the boundary
  they replace.
