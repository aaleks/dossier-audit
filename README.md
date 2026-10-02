# dossier-audit

Document collection and audit pipeline. Syncs documents from configured sources,
freezes them as immutable snapshots, converts them — to text, and to one picture
per page — runs a sequence of prompt stages over them, and scores the results
against human-verified answers.

Package and CLI: `dossier`.

**Status: implemented.** The specs came first and the code implements them —
see "How this is built" below. Where the rules stand is printed by
`pytest tests/architecture`, which counts them from `specs/` and so cannot fall
behind. This README keeps no figure of its own, because a figure here falls
behind with the next rule.

## Layout

| Path | What |
|---|---|
| `specs/` | The source of truth. Start at `specs/000-overview.md`, then `specs/README.md` for the index. |
| `CLAUDE.md` | The working agreement for this repository |
| `docs/architecture.md` | The two boundaries and the layer contracts |
| `docs/dossier-design-deck.pdf` | Background: the proposal this came from |
| `docs/jira-connector.md` | A tour of the Jira connector: what you write, and what a sync does |
| `docs/confluence-connector.md` | The same for Confluence: pages rendered for export, their files, a PDF where the server allows it, and the note a stage reads |
| `docs/web-connector.md` | The same for a website: one connector for every site, listed from its sitemap |
| `docs/review-in-mlflow.md` | Reviewing a run's answers in MLflow, for reviewers who never run `dossier`, and bringing their verdicts back |
| `docs/history/` | How it came to be: `slices.md`, what each slice changed and why, newest first; the first session's kickoff prompt; the brainstorm that led to page images; and the findings that led to the web connector |
| `src/dossier/` | The package: `domain/`, `application/`, `infrastructure/`, `config/`, `cli/` |
| `tests/` | `architecture/`, `unit/`, `acceptance/`, `integration/`, `evals/` |
| `playground/` | Hands-on exercises. Most run offline, in seconds, at zero cost; the rest need a Jira in Docker, a local MLflow server, a public site over the network, a Postgres and Ollama for the index, or Docling for OCR, and `playground/README.md` says which. Not part of `dossier`. |
| `dev/` | A Jira and a Confluence Data Center in Docker, to run a source against a server you can write to. Not part of `dossier` |
| `.claude/` | The spec-driven toolchain: skills, agents, rules, hooks |
| `.github/workflows/ci.yml` | The gate every pull request passes: the lock, conflict markers, ruff, the architecture tests, the default suite, and the outer loop reported beside them |

## Installing

```bash
pip install dossier            # markdown-text, text-plain, text-csv, html-markdown, png-pages,
                               # jira-issue-markdown, confluence-page-markdown
pip install dossier[pdf]       # and pdf-markdown, pdf-images, jpeg-pages
pip install dossier[tracking]  # and MLflow runs, traces and metrics
pip install dossier[docling]   # and docling-markdown: a PDF with no text layer, read by OCR
pip install dossier[browser]   # and render: browser, for a website that draws its pages in JavaScript
pip install dossier[index]     # and dossier embed and search: a Postgres + pgvector index to search by meaning
```

A `web` source that says `render: browser` has each HTML page drawn by a
headless Chromium, through Playwright. Install the browser once:

```bash
playwright install chromium-headless-shell   # about 115 MB; dossier never downloads it itself
```

Spec 001, R1.40-R1.43, and `docs/web-connector.md`.

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

The version is git's, not a number in `pyproject.toml` (R20.2). The commit
tagged `v0.2.0` installs as `0.2.0`, three commits past it as
`0.2.1.dev3+g<commit>`, and a checkout with uncommitted changes adds the date.
Every manifest and MLflow record names it as `dossier_version`. It is fixed when
the install is built, so run `uv sync` after a pull: it rebuilds the install
whenever the commit has moved. A copy with no git history, such as GitHub's zip
of a commit, refuses to build unless `SETUPTOOLS_SCM_PRETEND_VERSION` gives it a
version.

## Commands

```
dossier sync <pipeline>              # fetch only what changed
dossier sync <pipeline> --full       # ask every source for an unwindowed listing
dossier convert <pipeline>           # each document to the kinds its source declares
dossier run <pipeline> --plan        # what would run, and why
dossier run <pipeline>               # execute; writes runs/<id>/ as it goes
dossier run <pipeline> --doc KEY     # a try: ask about that document only; writes tries/<id>/
dossier run --replay runs/<id>/      # reproduce a past run exactly, with no model call
dossier calibrate <pipeline> --gold … # measure each judge against its human-scored sample
dossier eval <pipeline> --gold …     # score against verified answers
dossier eval <pipeline> --compare a b  # two runs, field by field, over the documents both answered
dossier dataset publish <pipeline> --gold …  # the gold set as an MLflow evaluation dataset
dossier prompts publish <pipeline>   # each step's prompt and each rubric as an MLflow prompt version
dossier review pull <pipeline>       # reviewers' verdicts from MLflow, into review/<pipeline>/
dossier review apply <pipeline> --gold … --verified-by …  # their expected values, into gold
dossier gc [--keep-last N] [--apply]  # preview, then delete old runs, tries, replays and unread cache entries
dossier status [<pipeline> --gold …]  # what each source holds, each latest run, what eval would withhold
dossier embed <index>                # documents and the latest run's grounded record, into a search index
dossier search <index> "<query>" --as <reader>   # the documents that answer it, for that reader, best first
```

A prompt is iterated on one document at a time. `dossier run <pipeline> --doc
KEY` is a **try**: every step is asked only about the named documents (a
`per_group` step about each one's whole group), and prints what a run prints.
Its answers are real, and cached under the keys a full run uses, so the next full
run is served them (R4.18, R4.21). A try is not a run, though. It writes under
`tries/<id>/` and no manifest under `runs/`, so `dossier eval`, `--plan` and the
"source has moved" warning still read the last full run (R4.20, R4.22). A step
that reads every document is skipped and says so (R4.23). In MLflow a try is
tagged `dossier.try`, and is not linked to a pipeline version as a run that
produced it (R4.24). A key no source holds stops the try before anything is
asked (R4.19). Two of `--plan`, `--replay` and `--doc` are two commands, and are
refused together rather than one being ignored (R4.26).

Nothing else deletes anything, so `runs/`, `tries/` and the cache only grow.
`dossier gc` reclaims the space without making a run it keeps impossible to
reproduce (spec 016). It keeps the latest five runs of each pipeline
(`--keep-last N`) and every run holding a `keep` file, which `--keep RUN`
writes. It deletes every other run, every try and every replay, and the cache
entries no kept run's replay reads. What a kept run needs is found by tracing
its own replay, so a kept run replays, and scores, after `gc` exactly as it did
before (R16.1). Converted documents the ledger holds now are kept too, and the
judge's verdicts, the embedding vectors and the snapshots are never touched.
When a kept run's conversions are gone, as after deleting
`.dossier/cache/convert`, its replay cannot be traced, so `gc` deletes no cache
entry, says which run stopped it, and `dossier convert` makes the run replay
again (R16.8). Without `--apply` it only
prints what it would delete and how much space that frees. With `--apply` it
holds the workspace's lock, so one started beside a `dossier run` is refused
rather than deleting what the run is writing (R20.1). With tracking on, each `--apply` is one
MLflow run in `dossier-audit/gc`, naming the runs it deleted (R11.28).

`dossier status` says what the workspace holds before anything is spent (spec
017). Each source's documents, active and tombstoned, when it last synced, and
each document a sync still owes it; each pipeline's latest run, its documents
and how many a step failed, or `failures not recorded` for a run that stopped
before it ended. With a pipeline and `--gold`, it names each judged field
`dossier eval` would withhold, in `eval`'s own words, because it asks `eval`'s
own gate, and a pipeline or gold set `eval` would refuse to score is refused as
`eval` refuses it. It changes no file, records nothing to MLflow, needs no server, and
exits 0 whatever it finds.

Every command that writes the workspace holds its lock, from before it reads
anything to its end: `sync`, `convert`, `run` (a try and a replay too), `embed`,
`gc --apply` and `review apply` (spec 020). A second one started beside it is
refused at once, exit 2, naming the first: `another dossier command is writing
this workspace: run, pid 4120, since 2026-10-02T07:30:12Z. Try again when it has
finished`. It never waits, so a daily job that finds yesterday's run still going
fails plainly rather than queueing behind it. The commands that only read --
`status`, `search`, `run --plan`, a `gc` preview, `eval` -- run beside a writer,
and see the workspace as it has left it so far. The lock is the operating
system's own, on `.dossier/lock`, and is let go when the process ends however it
ends, so a command killed halfway leaves nothing to delete (R20.1).

`dossier embed <index>` makes what the workspace holds searchable by meaning
and by words (spec 018). `indexes/<index>.yaml` names a pipeline, a pinned
embedding model and a chunker. Each document its sources hold active is cut at
its headings into chunks of at most `max_chars`, each carrying the headings above
it. Each chunk is embedded only when no vector is cached for that model and text,
and written to a Postgres + pgvector index that `dossier` owns. Fields the index
names are carried from the pipeline's latest run, reproduced from the cache as
`dossier eval` reads it (never from the copies under `runs/`, which are yours to
edit), but only when that run read the
snapshot held now, and only the values it grounded in the document:
categories as values to filter on, free text as a `record` chunk to search. A
second `embed` with nothing changed asks no model and writes nothing, because the
index is derived data, rebuilt from the workspace. Every source an index reads
declares who may read it (`acl:`), and is refused until it does. The connection
string is read from the environment variable the index names, never from the
file. Install the `index` extra; `dev/index` has a container to write to.

```yaml
# indexes/incidents.yaml
pipeline: incident-audit
embedding_model: ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
chunker: {name: headings, max_chars: 2000}
fields:
  filter: [severity, affected_systems]
target: {dsn_env: DOSSIER_INDEX_DSN}
```

`dossier search <index> "<query>" --as <reader>` asks the index a question in
plain words and lists the documents that answer it, best first (spec 019). It asks twice: by
meaning, the chunks nearest the query's vector, and by words, the chunks holding
every word of the query. The two ranked lists are fused by reciprocal rank, so a
chunk found both ways outranks one found only one way, and an incident key,
which nothing is near in meaning, is still found by its words. Each document is
listed once, at its best chunk, with the values the run carried; `--chunks`
lists the chunks instead. `--where severity=major` keeps the documents carrying
that value, in the spelling the declaration writes, and matched whole: a
`reference` field is one string, so a field filtered on each of its parts is
declared a `list`. A field the index does not filter on, or a value the field
does not declare, is refused before the model is asked. A search names the
readers it is for: `--as incident-response` keeps what that reader may read,
and `--as incident-response --as sre` what either may. The index's connection
string reads every row, so whatever holds it, a person or an agent searching
on someone's behalf, keeps readers apart this way, and a search naming no
reader is refused rather than listing every chunk. `--all-readers` searches
everything, and the first line says it was not filtered by reader. The query
is embedded after an instruction, as Qwen3-Embedding is trained to expect, which
`query_instruction:` in the index file may change, and its vector is cached, so
the same search again asks no model. A search of an index embedded with another
model than its file declares is refused, and one over documents synced since the
last `embed` says how many. `--json` prints the same results for a script. With
tracking on, each search is one MLflow trace, under no run.

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

Read page by page, a document still gives one answer per field. `dossier eval`
scores a field once per document. A page that abstains is passed over while
another page answers, and the field is correct only when every page that gave a
value is. A miss names its page (R7.46 – R7.49):

```
  resolution_date     83.3%   <- weakest
    PLAY-3005-weekly-incident-review.pdf page-002.png: '2026-09-02' does not match '2026-09-08'
```

A field the verified answers state and no page gave is a miss too, `not
answered`, in every mode (R7.50).

A list asks every document for every kind in it. A map asks a kind of one media
type only, and `[]` leaves a media type out (R8.26, R8.27):

```yaml
    convert:
      application/pdf: [markdown, page_images]   # the scans, as pictures too
      application/octet-stream: []               # held, and read by nothing
```

A source that declares no `convert:` is the automatic case: each document gets
the default kind for its media type (`page_images` for an image, `markdown` for
everything else) and the converter installed for it. A file nothing can read
then fails on its own, and the rest of the source is audited (R8.25). A kind a
source *declared* that nothing converts is a configuration error, and stops the
run before anything converts (R8.24).

That matters because not every document has a sentence in it. A figure drawn on a
chart is in no text, so a field citing it is **`described`** — neither a pass nor
a failure, because the evidence is on a page the model looked at and a string
search is the wrong instrument for it (R6.15). `dossier eval` puts such a field
to a judge with the document's pages in place of a transcript, and that judge is
calibrated and gated on its own threshold, separately from the one that reads
text (R7.20–R7.24).

A calibration reports more than its agreement, because the agreement figure hides
three things (R7.26–R7.29):

- how sure the figure is: 20 of 20 is 100%, and twenty cases support no more than
  83.9%;
- how much of it chance would give: a judge that calls every case supported
  scores 60% on a 12-to-8 sample, and its kappa is 0;
- which half of the sample the judge gets wrong.

```
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
```

The same figures go to the calibration file and the MLflow calibrate run. The
gate compares the agreement, and a gold set may add a bar for the half that
matters most: the share of unsupported cases a judge must catch, declared per
state beside the agreement bar (R7.30, R7.31):

```yaml
root_cause:
  grounded: 0.95
  described: {agreement: 0.90, unsupported: 0.875}
```

A judge at 90% that let two of eight invented causes through is then withheld:
`described: unsupported 6 of 8 (75.0%) is below the agreed 87.5%`. The lower
bound and kappa are reported only.

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

A document is not always one file. A supplier contract is a master agreement and
its amendments: the liability cap is in the master, and the renewal date is in
amendment 3. A `per_group` step asks one question per contract:

```
inbox/contracts/ACME-2024/master.pdf        group ACME-2024
inbox/contracts/ACME-2024/amendment-3.pdf   group ACME-2024
inbox/contracts/GLOBEX-2023/master.pdf      group GLOBEX-2023
```

A document's group is its key up to the first `/`, so no configuration names it.
Every connector already keys a file under what it belongs to, so a contract in its
own subfolder is a group, and so is a Jira issue with its attachments (R3.15).
Each group's call holds its members, each under its own key. The group's key
holds their inputs and no other document's, so an amendment filed in one contract
asks that contract again and no other (R5.14). A field cites the member its span
is in (R6.22), the answer is scored against a gold answer for the group (R7.32),
and a replay recomposes each group from the documents its manifest pins (R4.15).
A `per_file` step cannot read a group's answer, and is refused at load time
(R3.16).

Some documents are context rather than evidence. An incident says what
happened, and the escalation procedure says how fast it should have been
escalated. A pipeline names such sources under `reference:`:

```yaml
sources:   [incidents]
reference: [procedures]            # read, shown, cited; never audited
steps:
  - id: verify
    input: [documents, extract, reference]
```

A reference document is never itself asked about, filed or scored (R3.17).
`{{reference}}` holds every reference document, each under its own key, in
every call of every mode (R3.18). A step that reads it may cite a procedure. A
field of any step may cite only what its own call was shown, never another
document of the corpus, however true the quote (R6.23). Editing a procedure
re-runs only the steps that read it, and `--plan` says so first (R5.15, R4.17).
The manifest pins the reference documents apart, so a replay shows every call
the procedure as it was (R4.16). A judge is shown them beside the document
(R7.34). Reading `reference` in a pipeline that declares none is refused at
load time.

## What it records

With tracking on (`DOSSIER_MLFLOW_ENABLED=true` and a tracking URI, in the
environment or `.env`), `sync`, `convert`, `run`, `calibrate` and `eval` each record
one MLflow run, and each record says what it was made from. A `dossier search`,
which changes nothing, records one trace and no run:

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

MLflow is a place to **read** these, not a source `dossier` reads from. No
prompt, dataset or score is ever loaded back into a run: the files in the
workspace are the only source, which is what keeps a run reproducible from a
checkout (R14.5, R12.4). What `dossier` does ask MLflow is fenced, spec by spec:
a run, an eval and a calibration look up the prompt or rubric version they
rendered, by its hash; a run and an eval are handed the id of the pipeline
version they built or scored; an eval looks up its gold set's dataset. Each
answer reaches a link, a tag or the terminal, and never a key, a manifest or a
score (R0.17, R12.4, R13.4, R14.5).
Reviewers' verdicts are the one thing a person wrote that comes back, below,
and they are fenced too.

## Review in MLflow

People who never run `dossier` review its answers where the runs already are.
Each trace shows the document it read as its Request and the answer as its
Response (R15.1), and a run tags every trace it doubts, so
`` tags.`dossier.review` = 'needed' `` is a review queue anyone can open (R15.2).
Reviewers leave a thumbs-down with a reason, or the value that should have been
there. `dossier review pull` brings those back as a report by step and field --
where prompt work starts -- and as gold candidates (R15.3), which a maintainer
applies with `dossier review apply --verified-by <name>` as a signed, reviewable
change to the gold set (R15.4, R7.7). It is the only command that reads a
verdict back, and nothing it reads reaches a key, a manifest or a score (R15.5).
`docs/review-in-mlflow.md` is the tour, for reviewers and maintainers both, and
`playground/14-*` walks it.

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
pytest -m live          # the evaluated rules, Docling's models, Chromium and the
                        # Postgres index. Run deliberately
```

The default suite blocks network access outright — an autouse fixture refuses
socket creation for any test not marked `live`. That is not test hygiene, it is
R0.17: exactly four packages may reach the network, and everything right of that
line is a pure function of content hashes, which is what makes a run from six
months ago reproducible.

`pytest tests/architecture` is the mechanical half of the working agreement. It
walks every module with `ast` to check the hash boundary and the layer contracts,
and it checks that every spec rule and every test file still refer to each other.

## Learning it by running it

`playground/` has exercises that build a workspace, sync a folder, define a
pipeline, ground an answer, calibrate a judge, read the run back in MLflow,
audit a chart, sync a real Jira, publish a gold set, follow a regression
through MLflow to the prompt that caused it, review answers in MLflow, read a
public Confluence, ask one question of several files, check documents
against procedures, read websites, score answers that are not text, build and
ask a search index, say what a run cost and make it faster, and read a
photocopy back into text with OCR. Most run offline against a stub model server in
`playground/toolkit/`, so the code path is the real one and the answers are
yours to control. The exercise on Jira brings up a Jira Data Center in Docker
-- still on the stub model, with only the source real -- because a named
credential, someone else's version marker and a listing that cannot report a
deletion have nowhere to show themselves until a source is remote. The ones on
datasets, prompts and review need a SQL-backed MLflow server on your machine,
because datasets, prompt versions and logged models live in its tables. The
index exercises need the Postgres in `dev/index` and a local Ollama, and the OCR
one needs the `docling` extra and Docling's weights. Start at
`playground/README.md`, which says what each one needs.
