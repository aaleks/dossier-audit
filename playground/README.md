# The dossier playground

Ten hands-on exercises for learning `dossier` by running it: syncing a source,
converting PDFs, defining a pipeline, grounding an answer, scoring against a gold
set, calibrating a judge, reading the whole thing back in MLflow, and auditing
documents whose evidence is a chart rather than a sentence.

Everything here runs **offline, in seconds, at zero cost**. No API key, no model
bill, no network. A stub model server in `toolkit/` answers the same
OpenAI-compatible route a real endpoint would, from a file of rules you can read
and edit — so the code path is the real one and the answers are yours to control.

> This folder is practice material. It is **not** part of `dossier` and nothing
> under `src/`, `tests/` or `specs/` refers to it. It adds no rule, changes no
> behaviour, and is not governed by the spec-driven loop the rest of the
> repository is. See [Ground rules](#ground-rules) below.

## Before you start

```bash
uv sync --all-extras          # or: pip install -e ".[tracking]" and the dev group
.venv/bin/dossier --help      # sync · run · convert · calibrate · eval
```

Every exercise assumes you run `dossier` from a **workspace**: a directory
holding `sources.yaml`, `pipelines/`, your documents, and the `.dossier/` state
the tool writes. The exercises build their workspaces under
`playground/work/<exercise>/`, which `playground/.gitignore` keeps out of git.

## The exercises

Work through them in order; each one assumes the previous. The rule ids in the
last column are the ones the exercise makes visible — look them up in `specs/`
when you want the reasoning behind what you just saw.

| # | Exercise | What you practise | Rules you will see |
|---|---|---|---|
| 01 | [First sync of a folder of notes](01-first-sync-a-folder-of-notes/) | workspace layout, `sources.yaml`, the ledger, the snapshot store, incremental sync | R2.14, R2.15, R2.11, R1.8, R3.1 |
| 02 | [A pipeline end to end on markdown](02-a-pipeline-end-to-end-on-markdown/) | `pipeline.yaml`, prompts, field declarations, `convert` / `run --plan` / `run` / `--replay` | R3.6, R6.10, R4.7, R5.5 |
| 03 | [PDF documents and a converter you write](03-pdf-documents-and-a-custom-converter/) | media types, the `(media type, kind)` pair, writing and registering a converter, version bumps | R8.5, R8.7, R8.2, R5.4 |
| 04 | [Plain text, images and unrecognised media types](04-plain-text-and-unrecognised-media-types/) | `text/plain`, an image that arrives as `application/octet-stream`, and what the honest fix is | R8.3, R2.16, R8.5 |
| 05 | [A gold set and `dossier eval`](05-a-gold-set-and-dossier-eval/) | writing verified answers, per-field scoring, normalisation, `--compare` between two runs | R7.2, R7.1, R7.3, R7.8 |
| 06 | [Grounding, abstention and the one retry](06-grounding-abstention-and-the-one-retry/) | ungrounded spans, bare nulls, the single retry, a document that fails | R6.4, R6.5, R6.2, R6.9, R7.4 |
| 07 | [Calibrating a judge](07-calibrating-a-judge/) | free-text fields, the calibration sample, thresholds, `dossier calibrate`, withheld fields | R7.13, R7.14, R7.15, R7.17, R7.18 |
| 08 | [MLflow tracing end to end](08-mlflow-tracing-end-to-end/) | switching tracking on, experiments, tags, one trace per (step, document), LLM spans, capture modes | R10.1, R10.2, R10.5, R10.8, R11.1, R11.4 |
| 09 | [Cache keys, determinism and replay](09-cache-keys-determinism-and-replay/) | what changes a key and what does not, replay, byte-identical keys across machines | R5.2, R5.3, R5.6, R4.6, R4.7, R5.9 |
| 10 | [Charts, screenshots and the `described` state](10-charts-screenshots-and-the-described-state/) | `page_images`, a `per_part` step, one call per page, the third grounding state, a judge shown the pages, a threshold per state | R8.10, R8.11, R8.12, R3.12, R6.15, R7.20, R7.22, R7.23, R4.14 |

## How an exercise folder is laid out

```
0X-name/
  README.md      the exercise: what to build, in tasks, with checkpoints. No answers.
  SOLUTION.md    the full walkthrough: every command, and the output to expect.
  resources/     material prepared for you -- stub replies, proposed gold answers, packages
  solution/      the finished files. Copy them in when you are stuck, or to check yourself.
```

The intended way to use them is to read `README.md`, try it, and open
`SOLUTION.md` when you are stuck or when you want to compare. Every command in
every `SOLUTION.md` was run against this repository, and the output shown is the
output it produced.

If you want to skip the typing entirely — to see a working end state before
building your own — each `SOLUTION.md` starts with a **Run the prepared answer**
block that copies `solution/` into a workspace and runs it.

## Shared material

```
corpus/incidents/      five markdown incident notes (PLAY-1001 … PLAY-1005)
corpus/scans/          two small PDFs and a PNG, from toolkit/make_sample_pdfs.py
corpus/observability/  five PDFs and a screenshot, from toolkit/make_observability_docs.py
toolkit/               the stub model server, and the two document generators
```

`corpus/observability/` is exercise 10's, and is the only material here whose
evidence is drawn rather than written: an APM latency chart, a Grafana JVM
memory panel, a Kibana error screenshot and a throughput chart, each inside a
PDF that also has a text layer — plus `PLAY-3006`, a PNG with no text layer at
all. Every one of them states a money figure on the panel and in no sentence,
which is what makes a field `described` rather than grounded (R6.15).

Both generators are reproducible: run either one twice and the bytes are
identical, because a document whose hash moved for no reason would make a
snapshot look edited (R0.4). `make_observability_docs.py --digests` prints each
page's sha256 as the shipped converters render it, which is where the page
numbers in exercise 10's reply file come from.

The repository's own PDF fixtures, under
`tests/fixtures/documents/postmortems/pdf/`, are real material too — fifteen
generated postmortems — and exercise 03 uses them.

### The stub model

```bash
.venv/bin/python playground/toolkit/stub_model.py \
    --replies playground/02-a-pipeline-end-to-end-on-markdown/resources/replies.json \
    --port 8099 --log /tmp/dossier-calls.jsonl
```

Then in the workspace's `.env`:

```
DOSSIER_OPENAI_URL=http://127.0.0.1:8099/api
DOSSIER_OPENAI_API_KEY=stub
```

`dossier` reaches a model through one OpenAI-compatible route (R9.12), and
*where* a model is served is per machine and in no cache key (R9.2) — which is
exactly why a stub can stand in for a real endpoint without changing a single
key. The model **identifier** in `pipeline.yaml` is in every key; the URL is not.

The stub answers from a list of rules, first match wins, and appends one JSON
line per call to its log. That log is how you count model calls, which is what
several rules are actually about: a second run asking nothing (R5.5), a judge
asked only on a miss (R7.18), one LLM span per call (R11.2).

A rule matches on substrings of the prompt, and may also match on a picture the
call carried, by the sha256 of its bytes. That is not decoration: a `per_part`
step sends the same prompt for every page, so the picture is the only thing
that differs between two of its calls — which is exactly what the stage key
says, holding the part by content hash and nothing else about it (R3.12). The
log records how many images each call carried and which, because "the pages
reached the model" is not something the text of a prompt can show.

It is an **endpoint**, never a provider. A provider is a package that declares a
`dossier.models` entry point (R9.1, R9.7); this is a few hundred lines of the
standard library pretending to be a server.

### Using a real model instead

Every exercise works against a real endpoint. Point `.env` at it as
`.env.example` describes, pin the model in `pipeline.yaml`, and expect the field
values and the judge's verdicts to differ from what `SOLUTION.md` shows — which
is itself worth seeing once you have the deterministic version working.

## Ground rules

Three of them, and each one is a rule of the repository rather than of this
folder:

1. **The playground never changes `dossier`.** No file under `src/`, `specs/` or
   `tests/` is touched by any exercise. Where an exercise runs into something
   that would need a change — an image type dossier does not recognise, for
   instance — the exercise ends in a written proposal, because behaviour that is
   not in a spec does not get implemented (`CLAUDE.md`).

2. **Verified answers are written by you, not by an assistant.** `gold/` holds
   the definition of correct, and `.claude/hooks/guard-edits.sh` blocks any agent
   from writing under it: "editing gold until a score passes is how a threshold
   dies (R7.7)". So exercises 05 and 07 ship their gold files, calibration
   samples and thresholds as **proposals** under `resources/`, and you copy them
   in yourself after reading them. That copy is the exercise, not a formality.

3. **Document keys here start with `PLAY-`.** The incident keys in `specs/` come
   from `specs/_fixtures.md` and are governed by it. Practice documents use their
   own namespace so the two can never be confused.

## Cleaning up

```bash
rm -rf playground/work                    # every workspace you built
uv pip uninstall dossier-pdf-playground dossier-text-playground   # exercises 03 and 04
```

**The uninstall is not optional if you share the environment with the test
suite.** Exercises 03 and 04 install converter packages, and a converter is
resolved from the installed environment — so `installed_converters()` then
returns three converters instead of one, and
`tests/acceptance/test_R004_7__replay_reproduces_a_past_run.py` fails on

```
assert {c["id"] for c in converters} == {"markdown-text"}
```

because the manifest now records the converters that were really installed. The
test is right and so is the manifest: what a run recorded depends on the
environment it ran in, which is exactly what that assertion is about. Uninstall
the packages, or install them into a throwaway virtualenv, and `pytest` is green
again.

`.dossier/`, `runs/`, `mlruns/` and `.env` are already ignored by the
repository's `.gitignore`, wherever they appear.
