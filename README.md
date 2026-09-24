# dossier-audit

Document collection and audit pipeline. Syncs documents from configured sources,
freezes them as immutable snapshots, converts them — to text, and to one picture
per page — runs a sequence of prompt stages over them, and scores the results
against human-verified answers.

Package and CLI: `dossier`.

**Status: implemented.** The specs came first and the code implements them —
see "How this is built" below. Where the rules stand is printed by
`pytest tests/architecture`, which counts them from `specs/` and so cannot fall
behind. This README can fall behind, so its figure carries a date. On 2026-09-24:

```
specs: 238 rules across 15 specs | 224 MET, 0 IN PROGRESS, 0 NOT MET, 14 SUPERSEDED
       235 deterministic, 3 evaluated
```

## Layout

| Path | What |
|---|---|
| `specs/` | The source of truth. Start at `specs/000-overview.md`, then `specs/README.md` for the index. |
| `CLAUDE.md` | The working agreement for this repository |
| `docs/architecture.md` | The two boundaries and the layer contracts |
| `docs/dossier-design-deck.pdf` | Background: the proposal this came from |
| `docs/jira-connector.md` | A tour of the Jira connector: what you write, and what a sync does |
| `docs/history/` | How it came to be: `slices.md`, what each slice changed and why, newest first; the first session's kickoff prompt; and the brainstorm that led to page images |
| `src/dossier/` | The package: `domain/`, `application/`, `infrastructure/`, `config/`, `cli/` |
| `tests/` | `architecture/`, `unit/`, `acceptance/`, `integration/`, `evals/` |
| `playground/` | Thirteen hands-on exercises. Ten offline, seconds, zero cost; the eleventh runs a real Jira in Docker; the last two need a local MLflow server. Not part of `dossier`. |
| `.claude/` | The spec-driven toolchain: skills, agents, rules, hooks |
| `.github/workflows/ci.yml` | The gate every pull request passes: the lock, conflict markers, ruff, the architecture tests, the default suite, and the outer loop reported beside them |

## Installing

```bash
pip install dossier            # markdown-text, text-plain, png-pages, jira-issue-markdown
pip install dossier[pdf]       # and pdf-markdown, pdf-images, jpeg-pages
pip install dossier[tracking]  # and MLflow runs, traces and metrics
pip install dossier[docling]   # and docling-markdown: a PDF with no text layer, read by OCR
```

`docling-markdown` is for a photocopy -- a scanned contract, a faxed incident
note -- which `pdf-markdown` converts to page anchors and nothing else. It claims
the same pair, so it is **opt-in**: a workspace chooses it by naming it at the top
of `sources.yaml`, and a workspace that names nothing converts as before.

```yaml
converters: [docling-markdown]
```

It never downloads a model. Docling reads a layout model and a table model, and
`docling-markdown` reads them at pinned commits from Docling's model folder,
checked by SHA-256. Fetch them once (the first PDF it meets names these commands
if you have not):

```bash
hf download docling-project/docling-layout-heron --revision 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8 --local-dir ~/.cache/docling/models/docling-project--docling-layout-heron
hf download docling-project/docling-models --revision fc0f2d45e2218ea24bce5045f58a389aed16dc23 --include "model_artifacts/tableformer/accurate/*" --local-dir ~/.cache/docling/models/docling-project--docling-models
```

It is slow -- about twelve seconds a page on a CPU -- and a conversion is cached,
so `dossier convert` is the place to pay for it once. Spec 008, R8.13-R8.15.

`jpeg-pages` is under the `pdf` extra despite its name: it decodes through
Pillow, which the PDF converters need anyway and nothing else in `dossier` does.
`png-pages` needs neither, because a PNG page image is the file it was given.

Converters, connectors and model providers are all resolved from entry points,
never hard-coded: what a run can read depends on what is installed, and the
manifest records which converters it actually used.

## Commands

```
dossier sync <pipeline>              # fetch only what changed
dossier sync <pipeline> --full       # ask every source for an unwindowed listing
dossier convert <pipeline>           # each document to the kinds its source declares
dossier run <pipeline> --plan        # what would run, and why
dossier run <pipeline>               # execute; writes runs/<id>/ as it goes
dossier run --replay runs/<id>/      # reproduce a past run exactly, with no model call
dossier calibrate <pipeline> --gold … # measure each judge against its human-scored sample
dossier eval <pipeline> --gold …     # score against verified answers
dossier eval <pipeline> --compare a b
dossier dataset publish <pipeline> --gold …  # the gold set as an MLflow evaluation dataset
dossier prompts publish <pipeline>   # each step's prompt and each rubric as an MLflow prompt version
```

## What it reads

A source declares the kinds it converts to, and a step names the kind it reads:

```yaml
# sources.yaml
  - id: postmortems
    type: folder
    path: inbox/postmortems/
    convert: [markdown, page_images]

# pipeline.yaml
  - id: extract
    input: documents@page_images
    mode: per_part
    output: schemas/incident.yaml
```

`markdown` is what a bare `documents` means, so every pipeline written before
kinds could be named still reads the same. `page_images` is one picture per page,
delivered as a single container of parts (R8.11); a `per_part` step is run once
per page, keyed and retried and cached per page (R3.12).

That matters because not every document has a sentence in it. A figure drawn on a
chart is in no text, so a field citing it is **`described`** — neither a pass nor
a failure, because the evidence is on a page the model looked at and a string
search is the wrong instrument for it (R6.15). `dossier eval` puts such a field
to a judge with the document's pages in place of a transcript, and that judge is
calibrated and gated on its own threshold, separately from the one that reads
text (R7.20–R7.24).

A step may be asked with its own model instead of the pipeline's -- a cheap one to
extract, a strong one to verify:

```yaml
# pipeline.yaml
model: anthropic:claude-sonnet-4-5-20250929   # every step that names none, and the judge
steps:
  - id: extract
    ...
    model: ollama:qwen2.5:7b@sha256:<64 hex>  # this step only
```

It is pinned and checked at load time like the pipeline's, each step is keyed
under the model it was asked with, and `--plan` and `--replay` read it back
(R3.14). A pipeline whose steps name none is exactly what it was.

## What it records

With tracking on (`DOSSIER_MLFLOW_ENABLED=true` and a tracking URI, in the
environment or `.env`), `sync`, `convert`, `run`, `calibrate` and `eval` each record
one MLflow run, and each record says what it was made from:

| Record | Links |
|---|---|
| `dossier run` | the prompt version each step rendered, and the pipeline version it built (a logged model, spec 013), which links the same prompts |
| `dossier eval` | the pipeline version it scored, the gold set's dataset when one is published, and the rubric version each judged field was judged with |
| `dossier calibrate` | the rubric version it measured |
| `dossier eval --compare` | both pipeline versions, the dataset when one is published, and the one rubric both sides were judged with |

A prompt version is found by the hash the run rendered, never by being the newest,
so a prompt edited since cannot attach its words to a run that never saw them
(R14.7). That is what lets a regression in a comparison be followed, link by
link, to the prompt text that caused it — `playground/13-*` walks exactly that.

MLflow is a place to **read** these, never a place `dossier` reads from. No
prompt, dataset or score is ever loaded back into a run: the files in the
workspace are the only source, which is what keeps a run reproducible from a
checkout (R14.5, R12.4).

Prompt and dataset names are global on a server. When two checkouts share one,
set `DOSSIER_MLFLOW_NAMESPACE` on each — `sandbox` publishes
`sandbox.incident-audit.extract` and the dataset `sandbox.incidents` — or the two
publish into one history (R10.13). The older `DOSSIER_MLFLOW_PROMPT_PREFIX`
namespaced prompts alone, and is refused by name if it is still set (R10.15).

## How this is built

Specification-driven, with a double TDD loop. The specs come first and the code
implements them; a rule that is not in a spec does not get built.

```
/discover ──▶ /accept ──▶ /tdd ─ /tdd ─ /tdd ──▶ /verify ──▶ /quality
   spec        outer         inner cycles          audit       report
               loop
```

- The **outer loop** is one failing acceptance test describing what a user
  observes. It carries `@pytest.mark.outer_loop` and stays red while the slice is
  built. Exactly one is open at a time, and the test suite enforces that.
- The **inner loop** is one unit test at a time, driven to green with the minimum
  code. The default suite is green at the end of every cycle.

Rule ids never move. A rule that stops being true is **superseded in place** and
names its replacement, because test filenames and other rules cite those ids,
and rewriting the text under one would leave every test citing it claiming to
prove something nobody agreed to.

## Running the tests

```bash
uv sync --all-extras    # extras and the dev group; `pip install -e ".[pdf,tracking]"`
                        # plus pytest and ruff does the same by hand

pytest                  # the default suite: offline, seconds, zero cost
pytest -m outer_loop    # the open slice, when there is one. Red until it lands
pytest -m live          # the evaluated rules, and Docling's models. Run deliberately
```

The default suite blocks network access outright — an autouse fixture refuses
socket creation for any test not marked `live`. That is not test hygiene, it is
R0.10: exactly three packages may reach the network, and everything right of that
line is a pure function of content hashes, which is what makes a run from six
months ago reproducible.

`pytest tests/architecture` is the mechanical half of the working agreement. It
walks every module with `ast` to check the hash boundary and the layer contracts,
and it checks that every spec rule and every test file still refer to each other.

## Learning it by running it

`playground/` has thirteen exercises that build a workspace, sync a folder,
define a pipeline, ground an answer, calibrate a judge, read the run back in
MLflow, audit a chart, sync a real Jira, publish a gold set, and follow a
regression through MLflow to the prompt that caused it. The first ten run offline
against a stub model server in `playground/toolkit/`, so the code path is the
real one and the answers are yours to control. The eleventh brings up a Jira Data
Center in Docker -- still on the stub model, with only the source real -- because
a named credential, someone else's version marker and a listing that cannot
report a deletion have nowhere to show themselves until a source is remote. The
twelfth and thirteenth need a SQL-backed MLflow server on your machine, because
datasets, prompt versions and logged models live in its tables. Start at
`playground/README.md`.
