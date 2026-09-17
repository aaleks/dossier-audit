# 08 · MLflow tracing end to end

**You will build:** a tracked workspace, and then read every command's record
back in MLflow — runs, metrics, traces and spans.

**You will learn:** how tracking is switched on and where records land, what each
command records, what one trace per (step, document) actually looks like, how to
stop document text reaching the server, and why the terminal and MLflow can never
disagree about a figure.

**Uses the stub model and an MLflow server.** Both are local.

---

## Background, in one paragraph

Tracking **observes** a run and is never an input to one. Switching it on changes
no manifest, no cache key, no artifact and no score (R10.4) — which is why it can
be off by default and switched on for the run you care about. MLflow is "a second
place to read a figure, never a second way of arriving at one" (spec 011): every
number recorded is a number the command already printed, handed to the recorder
rather than computed again.

---

## Setup

```bash
# an MLflow server, from the repository root
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/08/mlflow.db \
  --default-artifact-root $PWD/playground/work/08/mlartifacts \
  --host 127.0.0.1 --port 5000
```

Start from a copy of your exercise 07 workspace, and add to `.env`:

```
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5000
```

Open `http://127.0.0.1:5000` in a browser. You will be reading everything below
there as well as from the CLI.

## Task 1 — the switch, and two refusals

Before running anything, break the configuration twice:

1. Set `DOSSIER_MLFLOW_ENABLED=yes`.
2. Set it back to `true` and point `DOSSIER_MLFLOW_TRACKING_URI` at a port with
   nothing behind it.

**Checkpoint.** Both are refused with exit 2, **before any work**. The second is
R10.5 and it is the one that matters: an hour of model calls nobody can inspect
afterwards is the failure it prevents. The first is R10.1 — a typo is refused
rather than read as "off", because a silently disabled tracker is discovered only
after the run it should have recorded.

Also worth trying: set MLflow's own `MLFLOW_TRACKING_URI` in your shell and
nothing else. It switches nothing on. Only `DOSSIER_` variables are read, so a
variable left over from another project cannot start recording your audit
somewhere you did not choose.

## Task 2 — one experiment per command

Run the whole cycle with tracking on: `sync`, `convert`, `run`, `calibrate`,
`eval`. Then look at the experiment list.

**Checkpoint.** Five experiments, one per command kind. Work out where those
names came from, then change the template — `DOSSIER_MLFLOW_EXPERIMENT` — to put
everything in one experiment, and find the two tags that keep it filterable
(R10.2, R10.3).

Then break the template on purpose: use `{source}` in it, and then use `{gold}`
for `dossier run`.

**Checkpoint.** Both refused, naming the variable to fix. A template rendered
literally would create an experiment nobody meant, and records would pile up in
it unnoticed.

## Task 3 — what each command records

For each of the five experiments, find the run and read its params and metrics.

**Checkpoint, roughly:**

| command | what the record holds |
|---|---|
| `sync` | per-source counts: known, changed, new, fetched, failed — and no traces |
| `convert` | per-source counts: held, converted, cached, failed |
| `run` | params (pipeline, model, pipeline hash), metrics (documents, cache_hits, model_calls, failed), the manifest as an artifact, and one trace per (step, document) |
| `eval` | one metric per scored field, plus `accuracy/overall` |
| `calibrate` | the agreement and the case count, plus one trace per sample case |

Two things to check rather than assume:

- Compare `sync`'s metrics with the lines `sync` printed in your terminal. Are
  they the same numbers, under the same names? (R11.4, and spec 011's whole
  point.)
- Run `eval` with a withheld judged field (exercise 07, task 5). Does
  `accuracy/root_cause` appear? Does `accuracy/overall` include it?

## Task 4 — read a trace

Open the `run` experiment, find the traces, and open one.

**Checkpoint.** One trace per (step, document), named `extract · PLAY-1001.md` and
tagged with both. Inside it:

- a **stage** span carrying `dossier.cache` (hit or miss) and `dossier.key`;
- an **LLM** span carrying the model and the attempt number.

Then run again, fully cached, and look at the new traces.

**Checkpoint.** Stage spans that say `hit`, and no LLM spans at all. A cache hit
is recorded as carefully as a miss: seeing that a document cost nothing is
information, and the key says which stored answer served it.

Now make one document fail (exercise 06's `replies-never-valid.json`) and find
the trace for it. What is the run's status in MLflow?

## Task 5 — keep the documents off the server

Set `DOSSIER_MLFLOW_CAPTURE=hashes`, clear the stage cache, and run again.

**Checkpoint.** The LLM span now carries the prompt hash, the input hashes and the
key — and no text at all. That is R10.8, and it is the setting you need when the
corpus is confidential and the tracking server is shared. Check that the span
still identifies the question exactly: the three hashes are the same three the
cache key is made of.

Also confirm what did **not** change: the run id, the manifest, the artifacts and
the cache keys are identical with tracking on, off, `full` or `hashes` (R10.4).
Prove it rather than believing it — hash the workspace, flip the setting, run
again.

## Task 6 — when traces do not arrive

On MLflow 3.x you may see, instead of traces:

```
WARNING mlflow.tracing.export.mlflow_v3: Failed to send trace to MLflow backend:
No Experiment with id=3 exists
```

The runs, params and metrics all land; only traces vanish. Investigate before
reading the solution — the question to answer is *which* tracking URI the trace
exporter is using, given that `dossier` passes its URI to `MlflowClient` and
deliberately never reads MLflow's own environment variables (R10.1).

**Checkpoint.** You can state the cause in one sentence, you have a workaround
that makes traces appear, and you can say what the right fix would be in a
repository where behaviour changes start as a spec amendment.

---

## Done when

- five experiments, each with the record its command printed;
- a trace you can read, with its stage span and its LLM span;
- text kept off the server, and a proof that keeping it off changed nothing else;
- an explanation for any traces that went missing.

**Next:** [09 · Cache keys, determinism and replay](../09-cache-keys-determinism-and-replay/).
