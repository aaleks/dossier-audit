# 02 · A pipeline end to end on markdown

**You will build:** a one-step pipeline that extracts four fields from each
incident note, and run it — convert, plan, run, replay.

**You will learn:** what a step is made of, the contract between a prompt and its
declared inputs, what a run writes, and why the second run costs nothing.

**The stub model is used from here on.** Start it before task 3.

---

## Background, in one paragraph

A step says: take *these inputs*, render *this prompt*, ask the pinned model, and
validate the answer against *this field declaration*. Three files, each with one
job. The field declaration is the interesting one: it is the only place field
names and kinds are written, and both the JSON Schema shown to the model and the
field list the scorer works from are generated from it — so they cannot disagree
with each other (R6.10). Nothing in a pipeline is Python: `dossier` never imports
an author's module to find out what they are extracting.

---

## Task 1 — the three files of a step

Start from your exercise 01 workspace, or build a fresh one at
`playground/work/02/` the same way. Add to `pipelines/incident-audit/`:

**`prompts/01_extract.md`** — must inject every input the step declares, and
nothing else. The step declares `input: documents`, so the prompt contains
`{{documents}}`. Write it so a model would know what evidence you expect with
each value.

**`schemas/incident.yaml`** — four fields, one kind each:

```yaml
fields:
  loss_amount:      {kind: amount, currency: CHF}
  resolution_date:  {kind: date}
  severity:         {kind: enum, values: [minor, major, critical]}
  affected_systems: {kind: reference}
```

Then break it on purpose, twice, and read what you get:

1. Rename `{{documents}}` to `{{docs}}` in the prompt and run any command.
2. Restore it, then declare a fifth field `root_cause: {kind: free_text}` with no
   `judge:`.

**Checkpoint.** Both are refused at load time, before anything runs, and each
message says what to fix. The first is R3.6 — an undeclared placeholder reaches
the model as six literal characters, and a declared input no placeholder uses
sits in the cache key doing nothing. The second is R6.10: a free-text field with
no rubric could only be string-compared, and that is the defect the declaration
refuses to allow. (You will add `root_cause` properly in exercise 07.)

## Task 2 — convert, and look at the text

```bash
dossier convert incident-audit
```

**Checkpoint.** `4 held · 4 converted · 0 cached`, and a second run of the same
command converts nothing and caches four. Find the converted artifacts under
`.dossier/cache/convert/` and read one. For a markdown source the conversion is
nearly a no-op — which makes this the right moment to understand why the step
exists at all, before exercise 03 points it at wiki exports and has you write a
converter of your own.

`convert` is optional: `run` converts what it needs anyway. It exists so the text
a stage will actually see can be inspected before a single model call is made.

## Task 3 — the plan, before the run

Start the stub model in a second terminal, from the repository root:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
    --replies playground/02-a-pipeline-end-to-end-on-markdown/resources/replies.json \
    --port 8099 --log /tmp/dossier-calls.jsonl
```

Copy `resources/env.sample` to `.env` in your workspace. Then:

```bash
dossier run incident-audit --plan
```

**Checkpoint.** It prints the pipeline, the document count, the model, and one
line per step — and writes nothing at all. Verify that last claim rather than
believing it: hash the workspace before and after (R4.6).

Read `resources/replies.json` before you go on. It is the model, and knowing
exactly what it will answer is what makes everything after this reproducible.

## Task 4 — the run

```bash
dossier run incident-audit
```

**Checkpoint.** `extract: 4 document(s) · 0 from cache · 0 failed`, and a run
directory under `runs/`. Open `runs/<run id>/manifest.json` and find:

- the pipeline hash, the model, and the prompt and schema hashes;
- the four documents, each pinned to a **snapshot hash**, not a path.

Beside it, `runs/<run id>/extract/` holds one file per document — the run's
artifacts, written as each document completed, with a `.meta.json` beside each
one (R0.11). Then find the same artifacts under `.dossier/cache/stage/`, keyed
rather than named, and compare the bytes. Every artifact has a provenance record
beside it; one without a record is not a cache entry at all (R0.3). Work out
which of the two copies a *replay* reads, and why the other one exists.

## Task 5 — the second run, and the replay

Run it again, then count the lines in the stub's call log.

```bash
dossier run incident-audit
wc -l /tmp/dossier-calls.jsonl
```

**Checkpoint.** `4 from cache`, and the log did not grow. The model was not
asked, because the key covering this step — prompt template, schema, model
identifier, input hashes — did not move (R5.5).

Now reproduce the first run from its manifest:

```bash
dossier run --replay runs/<run id>/
```

**Checkpoint.** `4 artifact(s) reproduced · no model calls · written to
runs/<run id>/replays/<replay id>/`. Note where that is: under the run it
reproduced, never over it (R0.12). Then note what it did *not* do — it never read
`pipeline.yaml`. A replay that consulted today's configuration would be
reproducing today's configuration, not the run (R4.7).

## Task 6 — make the model answer differently

Edit one reply in `resources/replies.json` — change `severity` for `PLAY-1001.md`
to `critical` — and run again.

**Checkpoint.** Nothing changes. The run is served from the cache, because the
model's *answer* is not part of the key; the question is. Work out which of these
would make it ask again: editing the prompt, editing the field declaration,
editing the note, changing the model identifier in `pipeline.yaml`, changing the
URL in `.env`. Try one, and keep the other four for exercise 09.

## Task 7 — a note with nothing in it

Put back whatever task 6 changed, so the four notes are served from cache again.
Then drop an empty file into the inbox, the kind an export that wrote nothing
leaves behind, and run the pipeline through again:

```bash
: > inbox/incidents/handover-note.md
dossier sync incident-audit
dossier convert incident-audit
dossier run incident-audit
```

**Checkpoint.** Exit 1, and the stub's call log did not grow:

```
  extract: 5 document(s) · 4 from cache · 1 failed
    extract failed on handover-note.md: every input it reads is empty: documents
```

- The note synced and converted without a complaint. Why is `run` the first
  command to refuse it? (R6.29)
- Asked anyway, the model would have abstained on every field, and been right.
  What would have been wrong with that?
- Run it again. The note fails again, still with no call, while the other four
  are served from cache. Why is there nothing to serve it?

Now replay the run that failed:

```bash
dossier run --replay runs/<run id>/
```

**Checkpoint.** `4 artifact(s) reproduced`, and no complaint about a missing
entry. The run wrote nothing for the note, so the replay does not look for
anything: it reproduces the failure (R4.7). Delete the note before the next
exercise.

---

## Done when

- a plan, a run, a cached second run and a replay, in that order;
- you can name the four things a stage key covers and one thing it does not;
- you can point at the file that decides what the model is asked to return;
- you can say why a document with nothing in it fails the run, when a model
  asked about it would have answered.

**Next:** [03 · Wiki exports, and a converter you write](../03-html-exports-and-a-converter-you-write/).
