# The dossier playground

Hands-on exercises for learning `dossier` by running it: syncing a source,
converting documents, defining a pipeline, grounding an answer, scoring against a gold
set, calibrating a judge, reading the whole thing back in MLflow, auditing documents
whose evidence is a chart rather than a sentence, auditing a real Jira running on
your own machine, publishing a gold set and a pipeline's prompts to MLflow, so a
regression can be followed to the words that caused it, letting people who never
run `dossier` review its answers in MLflow, and bringing what they say back into
the gold set under a maintainer's name, reading a public Confluence that belongs
to someone else without leaning on it, asking one question of a contract that
is several files, checking incidents against the procedures that apply to
them without auditing the procedures, reading three public websites as
documents, one of them drawn by a browser, scoring answers that are not text:
a yes or no, a length of time, and a list, indexing the notes to search them by
meaning, and asking that index questions, saying what a run cost and making it
faster, reading a photocopy back into text, masking a client's name before a model
sees it and keeping it masked all the way to MLflow and the index, and finally
looking after a workspace a job runs every day.

**Exercises 01 to 10, 12 to 14, 16, 17, 19, 22 and 27 run offline, in seconds, at zero cost.**
No API key, no model bill, no network. A stub model server in `toolkit/` answers
the same OpenAI-compatible route a real endpoint would, from a file of rules you
can read and edit — so the code path is the real one and the answers are yours
to control. Exercises 08, 12, 13 and 14, and task 7 of 22, also start a local
MLflow server; it is still your machine and nothing else. Exercise 27 also serves
a small website from your machine, on 127.0.0.1.

**Exercises 25 and 26 need the masking extras.** Presidio and spaCy, and spaCy's
four `lg` models, about 2 GB, installed once with `uv sync --extra masking --extra
masking-models`. After that they run offline, against the stub. Exercise 26's
task 4 starts a local MLflow server, and its tasks 5 to 7 need what exercises 20
and 21 need: the Postgres in `dev/index` and a local Ollama.

**Exercise 23 needs Docling.** The `docling` extra brings torch, and Docling's
model weights are downloaded once, at the commits `dossier` pins. After that it
runs offline, against the stub, and its first conversion takes between half a
minute and a few minutes on a CPU.

**Exercises 11, 15, 18, 20 and 21 are the exceptions, deliberately.** Exercise 11 brings up
a Jira Data Center in Docker, which costs an evaluation licence, about 4 GB of
RAM and an interactive setup wizard. Exercise 15 needs network access instead:
it reads two public Confluence servers anonymously, and asks them for three
pages, because the servers belong to someone else. Exercise 18 reads three public
websites the same way, and runs no model at all. Exercise 20 writes an index
to the Postgres in `dev/index`, in Docker, and embeds with a local Ollama's
`qwen3-embedding:4b-fp16`: about 10 GB of RAM between them, and no stub can
stand in, because a vector is only worth what the model meant. Exercise 21 asks
that index questions, and needs the same. In 11 and 15 the model is still
the stub; only the source is real. They come late because everything they
teach — a named credential, someone else's version marker, a listing that
cannot report a deletion, a payload that is mostly machinery — only exists once
a source is remote. Their `SOLUTION.md` files mark each block as run, derived or
shape, because a live server cannot produce the reproducible transcript the
others promise.

> This folder is practice material. It is **not** part of `dossier` and nothing
> under `src/`, `tests/` or `specs/` refers to it. It adds no rule, changes no
> behaviour, and is not governed by the spec-driven loop the rest of the
> repository is. See [Ground rules](#ground-rules) below.

## Watch first

[`tutorial/`](tutorial/) is an eight-minute narrated quickstart of what
exercises 01, 02 and 05 build: sync, convert, plan, run and eval, then a prompt
edit that `eval --compare` catches as a regression. An AI types every command
live, a voice says what each one is for, and every output is one the command
printed. Its README says how to render it with two commands. `TRANSCRIPT.md`
there is the same lesson as text, to type along with.

## Before you start

```bash
uv sync --all-extras          # or: pip install -e ".[tracking]" and the dev group
.venv/bin/dossier --help      # sync · run · convert · calibrate · eval · gc · status · embed ·
                              # search · dataset · review · prompts
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
| 02 | [A pipeline end to end on markdown](02-a-pipeline-end-to-end-on-markdown/) | `pipeline.yaml`, prompts, field declarations, `convert` / `run --plan` / `run` / `--replay`, a note with nothing in it | R3.6, R6.10, R4.7, R5.5, R6.29 |
| 03 | [Wiki exports, and a converter you write](03-html-exports-and-a-converter-you-write/) | the `(media type, kind)` pair, the two kinds of conversion failure and who chose the kind, writing and registering a converter for a pair `dossier` already answers, naming it and opt-in, a note that survives a page moving, why a register is not a table, version bumps and a cache that lies without one | R8.25, R8.24, R8.6, R8.7, R8.2, R8.13, R8.21, R8.22, R8.23, R6.4, R5.4 |
| 04 | [Media types, default kinds, and the file dossier will not read](04-media-types-and-the-file-dossier-will-not-read/) | where a media type comes from, why an image's default kind is not `markdown`, why a file nothing reads fails alone until a source declares its kind, leaving a media type out on purpose and what leaving out "unknown" costs, and what the honest fix is for a file nothing recognises | R2.16, R8.10, R8.25, R8.24, R8.26, R8.27, R2.21 |
| 05 | [A gold set and `dossier eval`](05-a-gold-set-and-dossier-eval/) | writing verified answers, per-field scoring, normalisation, `--compare` between two runs | R7.2, R7.1, R7.3, R7.8 |
| 06 | [Grounding, abstention and the one retry](06-grounding-abstention-and-the-one-retry/) | ungrounded spans, bare nulls, the single retry, a document that fails and says why, scoring and comparing a run with a failure | R6.4, R6.5, R6.2, R6.9, R7.4, R6.31, R6.32, R4.27, R7.52, R7.54, R7.55 |
| 07 | [Calibrating a judge](07-calibrating-a-judge/) | free-text fields, the calibration sample, thresholds, `dossier calibrate`, withheld fields, what an agreement figure hides, a judge nobody is serving | R7.13, R7.14, R7.15, R7.17, R7.18, R7.26, R7.27, R7.28, R7.29, R9.20, R11.23 |
| 08 | [MLflow tracing end to end](08-mlflow-tracing-end-to-end/) | switching tracking on, experiments, tags, one trace per (step, document), LLM spans, capture modes | R10.1, R10.2, R10.5, R10.8, R11.1, R11.4 |
| 09 | [Cache keys, determinism and replay](09-cache-keys-determinism-and-replay/) | what changes a key and what does not, replay, byte-identical keys across machines, what `gc` keeps | R5.2, R5.3, R5.6, R4.6, R4.7, R5.9, R16.1, R16.2, R16.3 |
| 10 | [Charts, screenshots and the `described` state](10-charts-screenshots-and-the-described-state/) | `page_images`, a `per_part` step, one call per page, the third grounding state, a judge shown the pages, a threshold per state, a bar for the unsupported half, one answer per document however many pages gave it, an enum's vocabulary and an answer outside it, a prompt tried on one document | R8.10, R8.11, R8.12, R3.12, R6.15, R7.20, R7.22, R7.23, R4.14, R7.30, R7.31, R7.46 – R7.50, R6.25, R6.26, R4.18 – R4.23 |
| 11 | [A real Jira on your machine](11-a-real-jira-on-your-machine/) | a remote authenticated source, a credential named and never written, issues and attachments as separate addresses, a listing that cannot report a deletion, which fields of an issue are the document, and naming the converter that answers | R1.1, R1.6, R1.8, R1.12, R1.13, R1.14, R2.6, R2.17, R2.18, R2.22, R8.13, R8.16 |
| 12 | [A dataset, and the change gate](12-a-dataset-and-the-change-gate/) | publishing a gold set as an MLflow evaluation dataset, what a record holds, a publish that sends nothing, a stale dataset, and a comparison recorded as per-field deltas | R12.1, R12.2, R12.3, R12.4, R12.5, R11.7, R11.8, R11.9, R11.10 |
| 13 | [Prompts and pipeline versions in MLflow](13-prompts-and-pipeline-versions-in-mlflow/) | publishing prompts and rubrics, a publish that sends nothing, which record links which prompt, links found by hash rather than recency, what a pipeline version is made of, one namespace for prompts and datasets, and a registry nothing reads back | R14.1, R14.2, R14.3, R14.4, R14.5, R14.7, R14.9, R14.11, R14.12, R10.13, R10.14, R10.15, R13.1, R13.2 |
| 14 | [Review in MLflow](14-review-in-mlflow/) | what a trace shows a reviewer, a review queue that is a filter in a URL, verdicts left by hand and through the API, what MLflow records about who left one, pulling them back as files `git` can diff, an override, candidates refused all at once, gold signed by a maintainer, and a run no verdict can move | R15.1, R15.2, R15.3, R15.4, R15.5, R7.7, R6.4, R7.4, R10.8 |
| 15 | [A public Confluence, read politely](15-a-public-confluence-read-politely/) | a CQL query, a page keyed by its id and versioned by its number, a page's files as documents of their own, the page as rendered and the note made from it, one version fetched as two snapshots and one note, a step that does not run for a document it cannot read, a refused export asked for again at every sync, a changed key that lists a source whole, and kinds asked per media type | R1.15, R1.16, R1.17, R1.18, R1.19, R1.20, R1.21, R8.19, R8.20, R2.3, R2.23, R2.24, R1.11, R3.11, R6.21, R6.20, R8.26 |
| 16 | [Several files as one document](16-several-files-as-one-document/) | a contract that is a folder of files, where a group comes from, one call per group, a key that holds the group's name, citing a member, gold per contract, an amendment that asks one contract again, a replay that groups what its run pinned, and the step that cannot read a group | R3.15, R3.16, R5.14, R5.10, R6.22, R6.3, R7.32, R7.33, R4.15 |
| 17 | [Procedures as context](17-procedures-as-context/) | `reference:` sources that are read and never audited, what `{{reference}}` holds in every call, a manifest that pins context apart, a tightened procedure that re-runs only the step shown it, a replay that reads the old procedure, citing only what a call was shown, and reading context nobody declared | R3.17, R3.18, R4.9, R4.16, R4.17, R5.15, R6.23, R6.3, R7.34 |
| 18 | [A website, read as documents](18-a-website-read-as-documents/) | a sitemap and its `<lastmod>`, a key for every page of a site, a note that is the page's `<main>`, a site with no sitemap listed by crawling, a crawl that fails rather than lists a part, a source that cannot be listed beside ones that can, a page drawn by a headless browser and what it may ask for, and a held source drawn once more | R1.29, R1.30, R1.31, R1.33, R1.36, R1.37, R1.38, R1.39, R1.40, R1.41, R1.43, R2.26, R2.27, R8.33 |
| 19 | [Answers that are not text](19-answers-that-are-not-text/) | a `boolean`, a `duration` and a `list`, a prompt that says how each is answered, `false` against `null`, why three months is not ninety days, one record per item scored as a set, item precision and recall, gold refused before scoring, a kind that is not there, and one question answered twice | R7.36, R7.37, R7.38, R7.40, R7.41, R7.43, R7.44, R6.24, R6.2, R7.3, R7.2 |
| 20 | [An index to search by meaning](20-an-index-to-search-by-meaning/) | an index declared apart from its pipeline, who may read a source, chunks cut at their headings and embedded with them, a vector cache that makes a second `embed` free, a search by words and a search by meaning and what each one misses, a run's categories carried only where grounded and only while the note is the one the run read, declarations refused before any work, an `embed` recorded in MLflow, and an index rebuilt from the workspace | R18.1 – R18.11, R11.33 |
| 21 | [Asking the index a question](21-asking-the-index-a-question/) | `dossier search`, the readers a search names and the one refused for naming none, a note listed once at its best chunk, a ranking by meaning and a ranking by words fused by reciprocal rank, what decides a tie, a key found by its words and a question found by meaning alone, chunks against documents, filters on a run's values and the spelling they are read in, readers, refusals before the model is asked, notes the index has not seen, the question's instruction and its cached vector, and a search recorded as one trace with no run | R19.1 – R19.4, R19.6, R19.7, R19.9 – R19.12, R11.35, R22.7, R22.9, R22.10, R11.37 |
| 22 | [What a run costs, and how fast it goes](22-what-a-run-costs-and-how-fast-it-goes/) | a step that names its own model, a model name refused because it moves, which keys a model moves and what the plan cannot know, tokens per step and per record, a retry that is paid for, "not reported" against nothing asked, `--concurrency` and `DOSSIER_CONCURRENCY` writing the same bytes faster, and a label, tokens and models in MLflow | R3.14, R3.4, R9.14, R5.13, R5.2, R5.11, R5.12, R9.18, R9.19, R9.17, R10.11, R11.20, R11.21, R11.22 |
| 23 | [A photocopy, read by OCR](23-a-photocopy-read-by-ocr/) | a PDF with no text layer, a workspace naming the converter that answers a pair, weights that are pinned and never fetched, OCR only where a page has no text layer, what OCR writes down and what it misses, a span that quotes the converted text and one that quotes the paper, and a converter name nothing answers | R8.1, R8.13, R8.14, R8.15, R8.2, R8.6, R8.9, R5.4, R6.4, R6.17 – R6.19 |
| 24 | [Two commands, one workspace](24-two-commands-one-workspace/) | the commands that write and the ones that only read, a second writer refused and told who, the holder's details beside the lock and the moment they are stale, a command killed halfway that leaves nothing to clean up, a daily job that fails plainly rather than waiting, and the version every record says it was written by | R20.1, R17.3, R5.2, R4.31, R20.2 |
| 25 | [A client's name, masked before it leaves](25-a-client-masked-before-it-leaves/) | what a model is sent and how to read it, declaring masking, numbered placeholders per document, a masked view's record and what it never writes down, a threshold that is required and a picture that is refused, a file named after the client, what the threshold decides, an allow-list for a word taken for a person, and what masking promises against what it measures | R21.1, R21.2, R21.4, R21.5, R21.7, R21.8, R21.9, R21.14 |
| 26 | [A client, masked all the way through](26-a-client-masked-all-the-way-through/) | where a masked view keeps the values it replaced, a value a person wrote masked with the note's own numbering, a value the note does not hold taking a new number, gold written against the original and compared masked, a judge calibrated on masked candidates, what MLflow records about masking and that it records no value, an index that holds no client data and an embedding model asked about none, an index whose masking never changes, and a search for a client by name | R21.15 – R21.25 |
| 27 | [A workspace that runs every day](27-a-workspace-that-runs-every-day/) | a page the sync still owes and the morning `status`, why `status` exits 0 with a problem in view, `status` and `eval` agreeing on a judged field, a `gc` preview proved to delete nothing, what `gc` keeps of a run it cannot replay, `--keep-last 0` refused before anything is read, a run directory losing its manifest last, and a record cut short | R17.1, R17.2, R17.6, R17.7, R16.5, R16.7 – R16.11 |

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
block that copies `solution/` into a workspace and runs it. Exercise 11 has no
such block: its workspace cannot run until a Jira exists to point it at, so its
`SOLUTION.md` opens by saying which of its blocks were run and which were not.

## Shared material

```
corpus/incidents/      four markdown incident notes (PLAY-1001 … PLAY-1004)
corpus/exports/        three HTML wiki exports and a CSV register (PLAY-4001 … PLAY-4004)
corpus/scans/          two small PDFs and a PNG, from toolkit/make_sample_pdfs.py
corpus/observability/  five PDFs and a screenshot, from toolkit/make_observability_docs.py
toolkit/               the stub model server, the two document generators, and
                       make_photocopies.py, which photocopies PLAY-3005 on demand
                       for exercise 23 rather than keeping 800 KB of pictures here
```

`corpus/incidents/` is used twice over, which is the point of using it twice.
Exercise 01 syncs those four notes from a folder; exercise 11's `seed_jira.py`
posts the same four into a live Jira and syncs them back out over HTTP. The
pipeline, the prompt and the field declaration are identical in both — so what
is left different between the two exercises is exactly what a remote source
costs, and nothing else.

`corpus/exports/` is exercise 03's: three wiki pages exported as HTML and a
register exported as CSV. `dossier` reads both formats out of the box, with
`html-markdown` and `text-csv` (R8.21, R8.23), so the exercise is about a
converter you write for a pair that is already answered. `PLAY-4003` is a
dashboard shared as a page whose body is one `<img>`, with no alt text, and it
holds no sentence at all, on purpose. `html-markdown` writes it as the name of
its image and nothing else (R8.22). Three of the four files are also test
fixtures, under `tests/fixtures/documents/exports/`.

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

`corpus/scans/` holds the two PDFs exercise 03 points at beside the exports — one
carrying an embedded image, one with no text layer at all — and the PNG exercise
04 uses. The repository's own PDF fixtures, under
`tests/fixtures/documents/postmortems/pdf/`, are real material too — fifteen
generated postmortems — and any exercise here can be pointed at them instead.

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

Two switches, both off unless given, make it more like a paid endpoint (exercise
22). `--usage` reports what each answer cost, at a made-up but fixed one token
per four characters; without it the stub reports nothing, and a run says
`tokens not reported` (R9.18). `--delay S` takes S seconds over each answer, so
`--concurrency` has something to win (R9.19).

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
   that would need a change — a file extension dossier does not recognise, for
   instance — the exercise ends in a written proposal, because behaviour that is
   not in a spec does not get implemented (`CLAUDE.md`). Exercise 04 shows one
   such proposal that was written, reviewed and landed as R8.10.

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
uv pip uninstall dossier-html-playground  # exercise 03
uv pip uninstall dossier-jira-playground  # exercise 11

# exercise 11's Jira, and both its volumes
docker compose -f playground/11-a-real-jira-on-your-machine/docker-compose.yml down -v
```

**Uninstall them if you share the environment with the test suite.** Exercises
03 and 11 each install a converter package, and a converter is resolved from the
installed environment. Both packages claim a pair `dossier` already answers. The
suite runs its R8.1 purity rows over every installed converter it has a sample
payload for, and it has one for HTML, CSV and a Jira issue, so both packages'
converters are checked for purity, and pass.

What decides the rest is opt-in. Exercise 11's package is not opt-in. None of
the workspaces the suite builds names either converter, so every test that
converts stops on

```
two converters claim the same pair, and picking either would be picking by
installation order:
(application/vnd.dossier.jira-issue+json, markdown) is claimed by both
jira-issue-markdown 1.1.0 and play-jira-issue-markdown 1.0.0
```

Exercise 03's solution package declares both its converters opt-in. They answer
only in a workspace that names them, and the suite is green with it installed.
A package you wrote for exercise 03 without `opt_in = True` fails as exercise
11's does, over `(text/html, markdown)`.

Uninstall the package, or install it into a throwaway virtualenv, and `pytest`
is green again. Do it for exercise 03's too: a converter belongs to the
workspace that names it, not to the environment the repository is tested in.

`.dossier/`, `runs/`, `mlruns/` and `.env` are already ignored by the
repository's `.gitignore`, wherever they appear.
