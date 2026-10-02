# 22 · What a run costs, and how fast it goes

**You will build:** this week's incident review. A cheap model reads each note,
and a stronger one writes the review's opening paragraph from everything the
first one extracted. Then you will ask the two questions every real audit gets
asked second, after "is it right?": what did it cost, and how long did it take?
And you will make it faster without changing a byte of what it writes.

**You will learn:** how a step names a model of its own, and which keys that
moves; why a model name that moves is refused before anything runs; where a
run says what it spent, step by step, and why a document served from cache
spent nothing; what a retry costs; why "tokens not reported" is not zero; how
`--concurrency` asks about several documents at once, and why nothing it
writes depends on it; and what MLflow records of all of it.

**Uses the stub model**, with two switches made for this exercise. `--usage`
makes it report what each answer cost, and `--delay` makes it take time over
each. Offline, about a minute. Task 7 also needs an MLflow server, as in
exercise 08, and is optional.

---

## Background, in one paragraph

Every exercise so far ran one model and printed no bill. A real audit runs
several models: a cheap one for the hundreds of calls that read one document
each, and a better one for the few calls that read everything. It pays for
each call, and waits for it. `dossier` reads what a provider says an answer
cost from the reply (R9.18), adds it up per step, and prints it. It also asks
about several documents at once if told to (R9.19). The stub's counts are made
up, at one token per four characters, so they come out the same on every
machine. `dossier` reads them exactly as it reads a provider's.

---

## Setup

Terminal 1, the stub, reporting what each answer cost:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/22-what-a-run-costs-and-how-fast-it-goes/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl --usage
```

Leave it running. Tasks 5 and 6 restart it with other switches.

## Task 1 — two steps, two models

Make a workspace under `playground/work/22/`. Copy `corpus/incidents/*.md` to
`inbox/incidents/`, and the `.env` from exercise 02's `resources/env.sample`.
Write `sources.yaml` with one `folder` source, `incidents`, over
`inbox/incidents/`.

Write `pipelines/incident-review/` with two steps:

- `extract`, `per_file` over `documents`, with exercise 02's prompt and
  `schemas/incident.yaml`. It names no model, so it is asked with the
  pipeline's: `model: openai:gpt-5.4-mini`.
- `summary`, `aggregate` over `extract`, with **no `output`**: its answer is a
  paragraph, not fields. It names a model of its own:
  `model: openai:gpt-5.4`. Its prompt asks for this week's incident review in
  three sentences, from `{{extract}}`.

Sync, then plan.

**Checkpoint.** Both steps are new, and the plan names `summary`'s model under
it:

```
! extract: new
! summary: new
      model: openai:gpt-5.4
```

- Why does the plan name `summary`'s model and not `extract`'s?

## Task 2 — one run, two models

Run it, then read the call log: one line per call, with the model each call
named.

**Checkpoint.** Four calls to `gpt-5.4-mini`, one note each, and one call to
`gpt-5.4` holding all four notes. The run prints a cost for each step:

```
  extract: 4 document(s) · 0 from cache · 0 failed · 1,573 tokens in · 644 out
  summary: 1 document(s) · 0 from cache · 0 failed · 1,285 tokens in · 61 out
```

Open the run's `manifest.json`. `summary` carries `"model": "openai:gpt-5.4"`,
`extract` carries no `model` at all, and the plan's `model` is the pipeline's.

- `summary` is one call, and it costs almost as much input as the four
  `extract` calls together. Why? What does its prompt hold?
- A step naming the pipeline's own model gives the same manifest and the same
  keys as naming none (R3.14 row 7). Why is that the right answer?
- When `dossier eval` puts a `free_text` field to a judge, which model judges
  it? (R3.14 row 11.)

## Task 3 — a name that moves

Change `summary`'s model to `openai:gpt-4o` and plan. Put it back, change the
pipeline's model to `openai:gpt-5-latest`, and plan again. Then put that back
too.

**Checkpoint.** Each is refused before anything runs, with exit 2, naming the
file, the line and the name:

```
pipeline.yaml, line 22: steps.1.model model 'openai:gpt-4o' is a name OpenAI moves to each new snapshot; ...
```

The call log still holds five lines.

- `gpt-5.4-mini` is accepted, and `gpt-4o` is refused. Neither has a date in
  it. What is the difference? (R9.14.)
- Suppose `gpt-4o` had been accepted. A month later OpenAI points it at a new
  snapshot. What would your cache serve, and under what key? (R0.6, R5.3.)

## Task 4 — which keys a model moves

Two changes, one at a time:

1. Change `summary`'s model to `openai:gpt-4o-2024-08-06` and plan. Put it back.
2. Change the pipeline's model to `openai:gpt-4o-mini-2024-07-18`. Plan, then
   run. Put it back, and run again.

**Checkpoint.**

1. `extract: cached` and `! summary: model changed`.
2. The plan says `! extract: model changed` and `! summary: upstream changed`.
   The run asks `extract` about all four notes, and serves `summary` from
   cache:

   ```
     extract: 4 document(s) · 0 from cache · 0 failed · 1,573 tokens in · 644 out
     summary: 1 document(s) · 1 from cache · 0 failed
   ```

   Put back, the run is served whole from cache, and prints no tokens at all.

- The plan said `summary` would run, and the run served it from cache. Was the
  plan wrong? What does `summary`'s key hold of `extract`, and when can that be
  known? (R5.2, R4.6.)
- Why did putting the model back cost nothing? (R5.13.)

## Task 5 — what it cost

Open the `.meta.json` files under your first run, `runs/<id>/extract/` and
`runs/<id>/summary/`. Each says how many attempts its answer took, and what
they cost.

Now make one note expensive. Restart the stub with
`resources/replies-retry.json` layered in front of `replies.json`, still with
`--usage`. In that file, PLAY-1003 answers with prose first and with fields
once it is corrected (exercise 06). Add a line to the end of
`inbox/incidents/PLAY-1003.md`, then sync and run.

**Checkpoint.**

```
  extract: 4 document(s) · 3 from cache · 0 failed · 911 tokens in · 184 out
  summary: 1 document(s) · 1 from cache · 0 failed
```

PLAY-1003's `.meta.json` says `"attempts": 2` and
`"tokens": {"input": 911, "output": 184}`. The call log's last two lines are
the two attempts.

Then restart the stub **without** `--usage`, add another line to PLAY-1003, and
sync and run again.

**Checkpoint.** `extract: 4 document(s) · 3 from cache · 0 failed · tokens not
reported`, and PLAY-1003's `.meta.json` says
`"tokens": {"input": null, "output": null}`.

- The 911 includes the attempt that was refused, and nothing it produced was
  kept. Why is it counted? (R5.11 row 2, R5.12 row 4.)
- The run in task 4 printed nothing about tokens, and this one prints `tokens
  not reported`. What is the difference? Why is neither `0 tokens`? (R5.12,
  R9.18 row 4.)
- Why is `summary` still served from cache, although a note changed?
- Tokens are in the record and never in a key. What would go wrong if they
  were in the key? (R5.11 row 6.)

## Task 6 — how fast

Restart the stub with `--usage --delay 1`, so each answer takes a second.
Delete `.dossier/cache/stage/`, then time a run. Delete it again, and time a
run with `--concurrency 4`. Compare the two runs' directories with `diff -r`.

Deleting the stage cache is safe for the next run, which asks again (R5.9). It
is not free for the runs before it: they can no longer be replayed (spec 016).
Here it is how you make the same run twice.

**Checkpoint.**

- The first run takes about 5.8 s and the second about 2.8 s.
- Both print the same counts.
- `diff -r` finds nothing but each file's `run_id`, and the manifest's
  `started_at`.

Then:

1. Try `--concurrency 0`.
2. Add `DOSSIER_CONCURRENCY=2.5` to `.env` and run.
3. Change it to `DOSSIER_CONCURRENCY=4`, delete the stage cache, and time a run
   with no flag.
4. Add `concurrency: 4` to `pipeline.yaml` and plan. Take it out again.

**Checkpoint.** 1 and 2 are refused before anything is asked, each naming
where the value came from. 3 runs in about 2.8 s. 4 is refused as a key a
pipeline does not have.

- Four notes were asked at once and the run took two seconds, not one. Where
  did the other second go, and would `--concurrency 40` win it back?
- The answers came back in whatever order the stub finished them. Why does
  nothing under `runs/` depend on that order? (R9.19 row 2.)
- Why is the number of documents asked at once a setting of the machine and
  the command line, and never of `pipeline.yaml`? (R9.19 row 8.)
- At `--concurrency 50`, a real provider answers some calls `429 Too Many
  Requests`. What does `dossier` do with a `429`, and how often? (R9.17.)

## Task 7 — what MLflow records (optional)

Start an MLflow server on a port of its own, so exercise 08's can keep running:

```bash
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/22/mlflow.db \
  --default-artifact-root file://$PWD/playground/work/22/mlartifacts \
  --host 127.0.0.1 --port 5001
```

Add to `.env`:

```
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5001
```

Delete the stage cache, run with `--label nightly`, and print what MLflow holds
with `resources/read_back.py`.

**Checkpoint.**

- The run is named `<run id> · nightly`, and its `dossier.label` tag is
  `nightly`.
- Its params include `concurrency` `4`, `model` `openai:gpt-5.4-mini` and
  `model/summary` `openai:gpt-5.4`.
- Its metrics are `tokens_in` 2883 and `tokens_out` 705.
- Each of the five LLM spans carries its own call's tokens and model.

Questions:

- `tokens_in` is the sum of which two numbers on the run's own lines? (R11.20.)
- A run served wholly from cache records `tokens_in` `0`, and a run against a
  stub with no `--usage` records no `tokens_in` at all. Why the difference?
  (R11.20 rows 4 and 5.)
- `concurrency` is a param of the run. Why is it in the record and in no key?
  (R11.21 row 5, R10.4.)

---

## Done when

- you can say which keys move when a step's model changes, and which when the
  pipeline's model changes;
- you can say why a moving model name is refused rather than warned about;
- you can read a run's cost per step, find it again in a `.meta.json`, and say
  why a retry is in it and a cache hit is not;
- you can tell "nothing was asked" from "the provider said nothing";
- you can make a run faster with `--concurrency` and show that it wrote the
  same bytes.

**Back to:** [the playground index](../README.md).
