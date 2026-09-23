# 13 · Prompts and pipeline versions in MLflow

**You will build:** a pipeline whose prompt and judge rubric are published to
MLflow's prompt registry, and a set of records — runs, versions, evals, a
calibration and a comparison — that each say which of those prompts they were
made with. At the end you can start from a regression in a comparison and click
your way to the two prompt texts that caused it.

**You will learn:** what a published prompt version holds and why it is tagged
with a hash, why publishing an unchanged prompt sends nothing, which record links
which prompt and why, why the link is found by hash rather than by recency, what a
pipeline version is made of, and why nothing a run does ever depends on what the
registry holds.

**Uses the stub model as both the extractor and the judge. Needs a SQL-backed
MLflow server.**

---

## Background, in one paragraph

A prompt is the input that changes most often and is read least easily. It is
hashed into every stage key (spec 005), and its hash reaches a provenance record
and a run's params in full — but a person looking at `b3c909cf` in
MLflow has no way to read the words behind it, or to diff them against the ones
that produced the run beside it. So `dossier prompts publish` sends each step's
prompt and each judged field's rubric to MLflow's prompt registry, versioned and
tagged with the hash that enters the key (R14.1–R14.3), and every record `dossier`
makes links the version it used: a run links the prompts it rendered (R14.7), the
pipeline version it built links the same ones (R14.12), and an eval, a
calibration and a comparison link the rubric they judged with (R14.9, R14.11).
The registry is a **projection**, one way only: `dossier` writes prompts to it and
never reads one back into a run (R14.5). That last sentence is the one to keep hold
of — MLflow's prompt registry exists to be loaded *from*, and `dossier` declines
exactly that half of it.

---

## Setup

This exercise gets a server of its own, so a registry that exercise 12 or your own
work has already published into cannot shift the version numbers you see. A prompt
name is global within a server (R14.8), and `incident-audit.extract` is a name
every earlier workspace would share.

```bash
# from the repository root
mkdir -p playground/work/13-server
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/13-server/mlflow.db \
  --artifacts-destination file://$PWD/playground/work/13-server/mlartifacts \
  --host 127.0.0.1 --port 5113
```

The stub needs exercise 07's rules, and exercise 12's override for the second
version of the prompt you will write in task 4. The override only matches a prompt
holding that version's extra line, so it can sit in front from the start:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/12-a-dataset-and-the-change-gate/resources/replies-prompt-v2.json \
  --replies playground/07-calibrating-a-judge/resources/replies-judge.json \
  --replies playground/07-calibrating-a-judge/resources/replies.json \
  --port 8113 --log playground/work/13-server/calls.jsonl
```

Build the workspace from exercise 07's material — the five notes, the verified
answers, the judge's rubric, its sample and its bar — with the **first** version
of the prompt (07's, without exercise 12's date line), in `playground/work/13/`.
The server's files sit beside it rather than inside it, so the workspace holds
nothing `dossier` did not write. Put in `.env`:

```
DOSSIER_OPENAI_URL=http://127.0.0.1:8113/api
DOSSIER_OPENAI_API_KEY=stub
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5113
DOSSIER_MLFLOW_EXPERIMENT_EVAL=dossier-audit/{pipeline}/eval/{gold}
DOSSIER_MLFLOW_EXPERIMENT_COMPARE=dossier-audit/{pipeline}/compare/{gold}
```

Then `sync`, `run` and `calibrate` once, **before publishing anything**. Note the
run id: this is run A, and it matters in task 2 that it happened first.

`resources/links.py` prints every prompt version, every run's linked prompts and
every pipeline version's linked prompts on a server. Use it at each checkpoint
alongside the UI:

```bash
.venv/bin/python playground/13-prompts-and-pipeline-versions-in-mlflow/resources/links.py \
  http://127.0.0.1:5113
```

---

## Task 1 — publish the prompts, and read one back

```bash
dossier prompts publish incident-audit
```

**Checkpoint.**

```
incident-audit · 2 prompts
  incident-audit.extract           b3c909cf  v1  created
  incident-audit.judge.root_cause  0443845a  v1  created
2 versions created, 0 unchanged
published to MLflow: http://127.0.0.1:5113
```

Open the Prompts page and read `incident-audit.extract` version 1.

- The name has a dot in it. What would the obvious spelling have been, and why
  is it not available? (R14.1.)
- The rubric is named after the **field** it judges, `root_cause`, not after a
  step. Two steps could declare one field. What would naming it after a step have
  done then? (R14.2.)
- Find `b3c909cf` on run A's record, which was made before anything was
  published. Where is it, and why is the tag on the prompt version the full 64
  characters rather than the eight the terminal shows? (R14.3.)

## Task 2 — publish it again, twice, and then run

Run the same command a second time. Then convert
`pipelines/incident-audit/prompts/01_extract.md` to Windows line endings (CRLF)
and publish a third time.

**Checkpoint.** Both times:

```
0 versions created, 2 unchanged
```

- MLflow's `register_prompt` creates a new version every time it is called, even
  for identical text. So how did nothing get sent? (R14.4.)
- The file's bytes changed with the line endings. Why is the prompt unchanged — and
  what does `dossier run incident-audit --plan` say about the key? (R14.3,
  R14.4 row 5, spec 005.)

Now run the pipeline again, and count the calls in the stub's log.

**Checkpoint.** `5 from cache`, and not one model call. Run `links.py`:

- Run A links nothing. The run you just made links `incident-audit.extract` v1.
  Why does run A not gain the link now that the prompt is published?
- Both runs built the **same** pipeline version — find its id. That version links
  `extract` v1, although it was built before the prompt was published. What made
  the link, and why is it right that a run which asked the model nothing can
  complete it? (R14.12 row 3.)
- The rubric was published too. Why is it not linked to the version? (R14.12 row 4.)

## Task 3 — the judge's standard, linked

Calibrate again, then score the run:

```bash
dossier calibrate incident-audit --gold gold/incidents
dossier eval incident-audit --gold gold/incidents
```

**Checkpoint.** 20 judge calls for the calibration, then `root_cause 100.0%
(4 judged)`.

- There are now two calibration records. Which one links
  `incident-audit.judge.root_cause`, and why not the other?
- The eval links the rubric. It also scored a pipeline version — does it link the
  step prompt to that version? What is the difference between making a version
  and measuring one? (R14.9, R14.12 row 5, R13.2.)
- The eval judged four candidates with the rubric's words **plus** a wrapper
  `dossier` puts around them. Is the wrapper in the linked version? Where would a
  change to it show up instead? (R14.9, R7.19.)

## Task 4 — a new prompt, a new version, and the old one kept

Add exercise 12's line to the prompt:

```
When you report a date, write dates exactly as the note writes them.
```

Publish, run (this is run B) and evaluate.

**Checkpoint.**

```
  incident-audit.extract           f92d511b  v2  created
  incident-audit.judge.root_cause  0443845a  v1  unchanged
```

and run B reports exercise 12's finding and scores `overall 92.0%`. Count the
judge calls that eval made, and explain the number. (R7.18.)

Then **take the line out again** — the prompt is back to exactly `b3c909cf` — and
run once more.

**Checkpoint.** `5 from cache`, no model call. Run `links.py`:

- Two pipeline versions now exist. Which prompt version does each link?
- The run you just made links `extract` **v1**, although v2 is the newest version
  of that prompt. Why is "newest" the wrong answer, and what would a person have
  been told if the link were taken from the top of the history? (R14.7 row 1.)
- Which pipeline version did that last run build, and why was no new one made?
  (R13.1.)

## Task 5 — the change gate, with its standard attached

```bash
dossier eval incident-audit --gold gold/incidents --compare <run-a> <run-b>
```

**Checkpoint.**

```
compare <run-a> -> <run-b> · 5 documents · overall 100.0% -> 92.0% (-8.0)
  loss_amount        100.0%  80.0%  -20.0   <- regression
  resolution_date    100.0%  80.0%  -20.0   <- regression
  ...
```

Open the comparison's run.

- It links the rubric **once**. Both runs were judged — why is one link right and
  two would be wrong? (R14.11.)
- `dossier.changed_steps` says `extract (prompt changed)`. Which two records does
  the comparison take as inputs, and what does each of them link?
- Now do the walk the whole exercise was for: from the comparison, to the version
  that regressed, to the prompt version it links, to a diff against v1 in the
  Prompts page. Which records did you *not* need to open, and what would you have
  needed without the links?

## Task 6 — two namespaces, one refused, and a registry taken away

A second checkout on another machine would publish `incident-audit.extract` into
the same history as yours. A prefix keeps them apart:

```bash
DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox dossier prompts publish incident-audit
DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox dossier run incident-audit
```

**Checkpoint.** `sandbox.incident-audit.extract` and
`sandbox.incident-audit.judge.root_cause`, each at v1, and the run links
`sandbox.incident-audit.extract` v1.

- The pipeline version the run found now links **two** prompts:
  `incident-audit.extract` v1 and `sandbox.incident-audit.extract` v1. Is that a
  mistake? What do those two have in common, and what is a version identified by?
  (R13.1, R14.8.)

Then try a prefix MLflow cannot hold:

```bash
DOSSIER_MLFLOW_PROMPT_PREFIX=team/a dossier run incident-audit
```

**Checkpoint.** Exit 2 naming the variable, no model call, and no new directory
under `runs/`. Why is this refused before the run does anything, rather than when
the name is first needed? (R14.10.)

Last: delete every prompt from this server — the UI's delete, or
`MlflowClient.delete_prompt` — then run `dossier run incident-audit --plan` and a
real run.

**Checkpoint.** `extract: cached`, `5 from cache`, no model call, exit 0 — and
the run's `extract/` artifacts are byte-identical to run A's. The run links
nothing, because there is nothing left to link. Why could deleting the registry
not change a single key or answer? (R14.5.)

---

## Done when

- two prompts in the registry whose versions you can read, each tagged with the
  hash that entered the key;
- a republish that sent nothing, including one across a line-ending change;
- a run, a version, an eval, a calibration and a comparison, each linking the
  prompt it was made with — and a run made before publishing that links nothing;
- a reverted prompt whose run links v1 and not the newest;
- a regression in a comparison you followed to the prompt text that caused it;
- a registry emptied, and a run that did not notice.

**Back to:** [the playground index](../README.md).
