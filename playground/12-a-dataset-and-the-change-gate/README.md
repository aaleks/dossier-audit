# 12 · A dataset, and the change gate

**You will build:** a gold set published to MLflow as an evaluation dataset, two
runs of the same pipeline that answer differently, and a comparison between them
that a person can open a month later and read.

**You will learn:** what a dataset record holds and why its only input is the
document key, why publishing an unchanged gold set sends nothing at all, what a
*stale* dataset is and why `dossier` names one rather than obeying or refusing it,
and why a delta belongs in an experiment of its own.

**Uses the stub model as both the extractor and the judge. Needs a SQL-backed
MLflow server.**

---

## Background, in one paragraph

Until now the gold set existed in two places: files in git, and a 64-character
hash tagged onto an eval run. That is enough to prove two evals measured the same
answers and not enough to *read* them. MLflow holds evaluation datasets as
first-class objects, so a gold set publishes as one: one record per verified
document, `expectations` holding the verified answers, tagged with the gold hash
and the reviewer behind it (R12.1, R12.2). An eval logs that dataset as an input
of its run, and so does a comparison, which means "every run measured against
these answers" is one filter rather than one hash lookup (R11.7, R11.10). The
dataset is a **projection**, one way only: it is written from `gold/` and read by
a person, and no score, key or file is ever computed from one (R12.4). That last
sentence is the one to keep hold of — a dataset holds the expected answers, which
is exactly what a scorer needs, and reading them from a server instead of from the
files would make a figure depend on what someone last published.

---

## Setup

Exercise 08's server will not do here unless it was started with a database. An
evaluation dataset lives in tables:

```bash
# from the repository root
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/12/mlflow.db \
  --artifacts-destination file://$PWD/playground/work/12/mlartifacts \
  --host 127.0.0.1 --port 5000
```

Start from a copy of your exercise 07 workspace — the four notes, the fifth that
07 adds, the verified answers, the judge's rubric, its sample and its bar — and
put in `.env`:

```
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5000
DOSSIER_MLFLOW_EXPERIMENT_EVAL=dossier-audit/{pipeline}/eval/{gold}
DOSSIER_MLFLOW_EXPERIMENT_COMPARE=dossier-audit/{pipeline}/compare/{gold}
```

Then `sync`, `run`, `calibrate` and `eval` once, so there is something to publish
against and a judge that has been measured.

**On Windows**, run the server with `--artifacts-destination` as a `file://` URL
as above. A bare `C:/...` path is read as a URI whose scheme is `c`, and traces
then fail to upload with *"Could not find a registered artifact repository"* while
everything else works — a confusing half-failure to debug later.

---

## Task 1 — publish the gold set, and read it back

```bash
dossier dataset publish incident-audit --gold gold/incidents
```

**Checkpoint.**

```
incidents · 5 records · digest 2fa4b927
published to MLflow: dossier-audit/incident-audit/eval/incidents (d-199062269f9b4e428a0f7260df6e231f)
```

Open the dataset in MLflow and answer these from what you see:

- Five records. What is in `inputs`, and what is *not*? Why can the snapshot
  address not live there? (Hint: MLflow merges a record onto the SHA-256 of its
  `inputs`. R12.2, R12.3 row 4.)
- Find `PLAY-1002`. Its `loss_amount` expectation is `null`. Why is that different
  from the field being absent, and what would be lost if publishing dropped it?
  (R7.3 row 4.)
- The dataset carries `dossier.gold_hash`, `dossier.snapshots_hash` and
  `dossier.verified_by`. Which of those three is *not* about the answers?

## Task 2 — publish it again, and watch nothing happen

Run exactly the same command a second time.

**Checkpoint.** Byte for byte the same line, the same digest, the same id. Now
answer the interesting part: MLflow's digest is
`sha256("<name>:<last_update_time>")` — it moves whenever the dataset is *written
to* and says nothing about what it holds. So why did it not move?

Then correct one answer in `gold/incidents/` — change `PLAY-1003`'s `severity`
from `critical` to `major` — and publish again:

```
incidents · 5 records · digest 3043d4a8
```

- Still five records, and a new digest. Which of the two tags from task 1 changed,
  and why does the record count not?
- What would a person comparing two dataset versions have seen if the second
  publish in this task had sent the same five records again? (R12.3.)

## Task 3 — the eval links what it scored against

Run `dossier eval incident-audit --gold gold/incidents` and open the run.

**Checkpoint.** The run's **inputs** show `incidents` and its digest, beside the
`accuracy/` metrics exercise 08 already showed you.

Read the scores too. You corrected `PLAY-1003` in task 2, and run A said what the
note says, so:

```
5 documents · 5 fields · overall 96.0%
  severity            80.0%   <- weakest
    PLAY-1003.md   'critical' does not match 'major'
```

The dataset and the files agree here, because you republished. Now break that:
change `PLAY-1003`'s `severity` back to `critical` — the reviewer thought again —
and run the eval **without** republishing.

**Checkpoint.**

```
dataset incidents is stale: published 1cdc3ac9, scored 8a13aeee
  run `dossier dataset publish` to refresh it
5 documents · 5 fields · overall 100.0%
```

- The eval still scored, and the figures are the *files'*: back to 100%, because
  the files say `critical` again. Does the dataset hold `critical` or `major` at
  this moment, and did that affect the number?
- Three things `dossier` could have done — refuse, republish, or link and say so.
  Argue for the one it does. What does R10.6 say about letting a tracking server
  decide whether a local score happens?
- You reverted an answer to exactly what it was, and `scored 8a13aeee` is neither
  of the two hashes you have seen. Why not? (The gold hash is over **bytes**, and
  rewriting a file does not reproduce its formatting — R0.7, R12.3 row 5. Publish
  again and watch a third digest appear for a set whose *answers* are the ones you
  started with.)

## Task 4 — three ways to be told no

Break the configuration three times. Each refusal names one thing to change, and
that is the whole point of the rule (R12.5).

1. `DOSSIER_MLFLOW_ENABLED=false dossier dataset publish incident-audit --gold gold/incidents`
2. Publish with `--gold gold/incident` — the `s` dropped.
3. Start a **second** MLflow server, file-backed, and publish at it:

   ```bash
   MLFLOW_ALLOW_FILE_STORE=true .venv/bin/mlflow server \
     --backend-store-uri file://$PWD/playground/work/12/filestore \
     --host 127.0.0.1 --port 5001
   ```

**Checkpoint.** Three different messages, none of them a traceback:

```
incident-audit: publishing a dataset needs tracking on: set DOSSIER_MLFLOW_ENABLED=true
and DOSSIER_MLFLOW_TRACKING_URI. A dataset is published to MLflow and nowhere else

incident-audit: no gold set at gold/incident

incident-audit: the MLflow server at http://127.0.0.1:5001 cannot hold an evaluation
dataset: /api/3.0/mlflow/datasets/search answered 500 Internal Server Error. Datasets
need a SQL backend -- start the server with --backend-store-uri (postgresql, mysql,
sqlite or mssql), not a file store.
```

A file store answers that endpoint **500**, not 404 — the route is there and the
handler fails inside it. `dossier` refuses on any answer that is not a success for
that reason; when it looked for 404 alone, the publish went through and MLflow's
client retried the 500 with backoff until the command appeared to hang. A refusal
names the fix; a hang names nothing.

Two questions worth sitting with:

- `dossier run` with tracking off runs perfectly happily. Why does `dataset
  publish` refuse instead? (What is this command's output?)
- Now run an **eval** against that same file-backed server. It scores, and says
  `dataset not linked: MLflow could not be asked for it`. Why is that the right
  asymmetry? (R12.5 row 5, R10.6.)

You needed `MLFLOW_ALLOW_FILE_STORE=true` to start that server at all: MLflow 3.15
puts the file store in maintenance mode. That is the same fact the refusal is
about, said by MLflow instead of by `dossier`.

## Task 5 — two runs, and the figure that hides a regression

Add a line to `pipelines/incident-audit/prompts/01_extract.md`:

```
When you report a date, write dates exactly as the note writes them.
```

Restart the stub with this exercise's override layered in front, and run again:

```bash
python playground/toolkit/stub_model.py \
  --replies playground/12-a-dataset-and-the-change-gate/resources/replies-prompt-v2.json \
  --replies <your exercise 07 replies.json> \
  --port 8099
```

**Checkpoint.** The run reports a finding before you score anything:

```
extract: 5 document(s) · 0 from cache · 0 failed · 1 finding(s)
  PLAY-1002.md  loss_amount: has a value and no source. A figure without evidence
                is the thing this system exists not to produce (R6.6).
```

Before comparing: the prompt changed, so why did this run ask the model again
instead of serving run A's answers from the cache? Which of the two — the rendered
prompt or the prompt template — is in the key? (Spec 005.)

## Task 6 — read the change gate in MLflow

```bash
dossier eval incident-audit --gold gold/incidents --compare <run-a> <run-b>
```

**Checkpoint.**

```
compare 20260922T055408Z-2071 -> 20260922T055516Z-d3cf · 5 documents · overall 100.0% -> 92.0% (-8.0)
  loss_amount        100.0%  80.0%  -20.0   <- regression
  resolution_date    100.0%  80.0%  -20.0   <- regression
  severity           100.0% 100.0%   +0.0
  affected_systems   100.0% 100.0%   +0.0
  root_cause         100.0% 100.0%   +0.0
recorded to MLflow: dossier-audit/incident-audit/compare/incidents
```

Open that experiment and read the run.

- Three metrics per field — `a/`, `b/` and `delta/`. Why record both sides when the
  delta is the figure the change gate exists for? What would you have to open to
  read `-20.0` without them?
- `dossier.regressed` is `loss_amount, resolution_date`. Build the MLflow filter
  that finds every comparison in which `affected_systems` regressed. Then consider
  what an *absent* tag would have meant on a comparison where nothing regressed.
- Why is this run in `compare/` rather than beside the evals? Put
  `accuracy/severity` and `delta/severity` in one experiment in your head and say
  what goes wrong.
- The two fields regressed for different reasons: one value is unreadable and the
  other is ungrounded. Find both in the eval output. Does a comparison say which is
  which — and should it?

Two more things this run holds that are easy to miss: the params name **each run's
own pinned model**, not one model, and the dataset is linked here exactly as it was
on the eval (R11.10). Change the pipeline's `model:` and you have the comparison
the change gate was built for.

---

## Done when

- a dataset in MLflow whose five records you can read, including a verified `null`;
- a republish that sent nothing, and a correction that moved the digest;
- a stale dataset named on a run whose figures came from the files;
- three refusals, each naming one thing, and an eval that shrugged at the third;
- a comparison you can find months later by the field that regressed.

**Back to:** [the playground index](../README.md).
