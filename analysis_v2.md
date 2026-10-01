# dossier — an outside review, v2

> Written 2026-10-01 against `main` at `bac80ef` (#674). Like v1, this is an
> opinion document and not a spec: nothing here is a rule, and anything worth
> building goes through `/discover`.
>
> `analysis.md` (v1, 2026-09-23, `f7d0ac2`) stays as it was. **v2 lists only
> what is still open or newly found.** Of v1's 35 recommendations, 23 have
> landed and are not repeated here. An item carried over from v1 says so
> (v1 §n).
>
> One change landed after this base. #675 opened R19.10–R19.12 and R11.35, all
> NOT MET: a search names its readers, for an agent that will search on
> people's behalf. Readers are kept apart by the application, never by
> Postgres roles. Row-level security was measured, and the words list lost its
> GIN index under it. The counts below are as of `bac80ef`.

## TL;DR

- **The product gaps v1 named are closed.** In eight days the rule count went
  from 205 to 419 across 20 specs. Every rule is MET or superseded, and CI
  gates every pull request in about three minutes. Grouping, the new field
  kinds, concurrency, retries, tokens, review, OCR, judge statistics, `gc`,
  `status`, `embed` and `search` all landed.
- **The risk has moved: dossier is now built ahead of its evidence.** Every
  question the specs still hold open waits on a real corpus (spec 003 Q2,
  spec 019 Q1 and Q2). The largest live check in the history is a 91-page web
  sync, and the stage runs checked live used playground corpora of a handful
  of documents. Only 3 of the 419 rules are `evaluated`, and all three are
  about judges. Nothing yet measures whether the shipped pipeline extracts
  well, or whether search finds the right incidents. **The next step is a
  pilot, not a spec.**
- **What a real corpus will hit first** (§3.2):
  - One document the model refuses, for example because it is too long,
    stops the whole run, and every rerun stops at the same document.
  - Every page image is loaded before the first call.
  - An `embed` that fails in its last batch keeps none of its vectors.
  - Nothing locks one command against another: spec 016 says `gc` beside a
    run deletes what the run is writing.
- **Four bugs the green suite does not see** (§3.5):
  - `gc` compares the wrong hash.
  - A reply cut off for length is cached as an answer.
  - One damaged `manifest.json` stops five commands.
  - A damaged page container drops a document without a word.
- **`dossier_version` has read `0.1.0` in every record for all 858 commits.**
- **One cheap cost lever is unused.** Reference documents are identical in
  every call, byte for byte (R3.18 row 2), which is exactly what provider
  prompt caching discounts. But the prompts put them last, and no provider call
  asks for caching.
- **Search exists, and nothing measures it.** A relevance gold set and an
  `evaluated` rule should come before any decision on BM25 or reranking.
- **Frameworks.** v1's verdict holds for the core, and the one adoption since,
  Docling, went well. Worth adopting now, at the edges: **fsspec** for object
  storage sources, **Docling's Office backends**, a workspace **file lock**, and
  **hatch-vcs** for the version. Worth adopting only after measurement:
  **pg_textsearch** (BM25), a **reranker served by vLLM**, and **GEPA** as an
  offline prompt proposer. Still no: LangChain, LlamaIndex and Haystack,
  orchestrators, eval frameworks, LiteLLM.

---

## 1. Where it stands

| | v1 (2026-09-23) | Now (2026-10-01) |
|---|---|---|
| Specs | 15 | 20, all `Implemented` |
| Rules | 205, 194 MET | 419: 401 MET, 18 superseded, 0 open; 416 deterministic, 3 evaluated |
| `src/` | ~15.3k lines | ~29.0k lines, 118 files |
| `tests/` | ~43k lines, 262 files | ~82.7k lines, 528 files, 2,799 test functions |
| Spec text | ~6.8k lines | ~13.9k lines |
| Commits | 464 | 858 (28 to 63 a day since 2026-09-22) |
| Commands | sync, convert, run, eval, calibrate | + `status`, `gc`, `embed`, `search`, `dataset publish`, `prompts publish`, `review pull` and `apply`; `run --doc`, `--plan`, `--replay` |
| Sources | folder, Jira | + Confluence, web (with browser rendering) |
| Models | | anthropic, openai, gemini, hf, ollama; embeddings: ollama |
| Playground | 12 exercises | 21 |
| CI | untracked | every PR: conflict markers, ruff, architecture, the suite; outer loop reported |

The engineering habits v1 praised have held up under twice the size: rules
superseded in place, a live check per slice that keeps finding what fakes
hide, and mutation passes on each new `domain/` module.

---

## 2. Still open from v1

Only the items that have not landed. "Pilot" means: decide after the pilot in
§4 has produced numbers.

| Item | v1 | Where it stands | My view now |
|---|---|---|---|
| Provider batch APIs for backfills | §4.1 | Not built. Concurrency and transport retry landed (R9.19, `domain/retries.py`) | Keep, after the pilot shows a backfill large enough to matter. Same shape: submit every miss of a step, fill the cache when the batch completes |
| Cost in money | §4.2 | Tokens are recorded (R5.11, R9.18). There is no price, no estimate and no stop | Keep. Prices are declared by the user per model, never typed in by dossier. `--plan` estimates from the tokens the same step recorded before; `--max-cost` stops a run |
| Long documents: split, then gather | §4.4 | Spec 003 Q2 is OPEN: "needs a real contract corpus" | Pilot. Build it when a real call fails for length |
| Nested records | §4.4 | Not built | Defer. Only the contract case needs it |
| A near-match grounding state | §4.7 | NFKC, de-hyphenation and quote folding landed (R6.17, R6.18). Fuzzy alignment did not | Pilot. Sample 50 ungrounded fields from a real run and count the honest citations that were missed. Build it only if that share is real |
| `dossier init` | §4.9 | Not built. The playground is the onboarding path | Keep, small: scaffold from exercise 02's solution |
| `run --sample N` | §4.9 | `--doc` landed (R4.18); `--sample` did not | Drop unless asked |
| `dossier diff` between runs | §4.9 | `--compare` is per field (R7.8); `eval` names the documents behind each miss (R7.25) | Drop unless a reviewer asks for it |
| Prompt optimisation and judge alignment | §4.10 | Not built | Keep, now more viable: `review pull` grows the gold set. See §5.3 |
| Multimodal page embeddings | §6.9 | Not built | Defer |
| Retrieval as a stage input | §6.8 | A decision, not taken | **Changed view:** do prompt caching first (§3.3). It removes most of the cost argument for retrieval. Retrieve only when a reference set no longer fits in context. If it is ever built, v1's constraints still hold: an exact local search over cached vectors, its ordered ids cached as an artifact, and **not** `dossier search`'s approximate HNSW path |

---

## 3. New findings

### 3.1 Built ahead of evidence

v1's concern was that MLflow work crowded out product gaps. That is resolved:
the gaps were built. The concern now has a different shape.

- **Every open question left in the specs waits for data dossier has never
  read.** Spec 003 Q2 (a group larger than a model accepts), spec 019 Q1 (is
  100 candidates enough) and Q2 (any word or all words) all say "needs a real
  corpus". So does the `ts_rank_cd` tie observation in spec 019's history.
- **The evaluated half is thin.** Three rules are `evaluated`: R7.11, R7.12 and
  R7.24, and all three are about judges. The 416 deterministic rules prove the
  machinery: that a key moves when it should, or that a replay asks nothing.
  No rule says that the incident pipeline answers well on real incidents, and
  none says that search ranks the right incident first. Those are the two
  claims a user would buy dossier for.
- **Specs land faster than they are used.** Specs 016 to 019 landed in two
  days. Each is careful, but none has yet been used by someone other than its
  author on their own data. Another spec now costs more than it did in v1,
  because each rule adds to what every later change must keep true.

The fix is not to slow the loop. It is to point it at a real corpus once,
measure, and let the numbers order the remaining work (§4, step 1).

### 3.2 Scale: what a real corpus will hit

Two cases: 5,000 Jira issues, and 400 PDF contracts of 60 pages each, on a
16 GB laptop. The size and time figures are estimates from reading the code,
not measurements, and measuring them is part of the pilot. The first four I
checked line by line.

| # | Limit | Where | At that scale | Shape of the fix |
|---|---|---|---|---|
| 1 | **One document's refused request stops the whole run.** Any non-2xx is `ModelRequestFailed` (R9.12 row 4), and it leaves `execute` uncaught, so `dossier run` exits 2 (`cli/run.py:586-591`, `MODEL_FAILURES` in `cli/bootstrap.py:62`). A 400 for a prompt over the context window is not retried, and rightly so (`domain/retries.py:44`) | `application/extract.py:249-262` re-raises | Document 3,000 is too long, so the run stops there. The rerun serves 2,999 from cache and stops at the same document. The corpus cannot get past it without editing the source | A refusal about **this request** (400 or 413) fails that document into `failures.json`. A refusal about **the endpoint** (401, 403, 404, 5xx after retries) still stops the run. A spec amendment to 009 |
| 2 | **Ollama is sent no `num_ctx`** | `infrastructure/models/ollama.py:98` sends only `temperature` | Ollama cuts a prompt longer than its context window without failing, so a long contract is answered from part of itself | Send `num_ctx` from the pin, or refuse a prompt larger than it |
| 3 | **Every page image is in memory before the first call, held twice.** `ConvertReport` keeps each container (`application/convert.py`), and `cli/run.py:467-475` unpacks every part into new `bytes` | The same full load repeats in `eval` (twice for `--compare`), `embed`, and `gc` per kept run | 24,000 pages at roughly 0.2-0.5 MB (text) or 1-4 MB (scans) each, held twice: well past 16 GB | Pass a cache key and a part index, and unpack one document inside the call that needs it |
| 4 | **`embed` caches nothing until every batch has answered.** The vectors are kept after the last batch, by design: their lengths are checked first (`application/embed.py:208-236`) | Batches of 32, sent one after another | A timeout in batch 2,000 discards every vector of that `embed`, which is hours on a CPU (spec 018 Q1 measured 21 chunks in 76 s, model load included) | Check the length per batch against the first vector, and cache each batch as it lands |
| 5 | **Conversion is sequential, and Docling reads one page per conversion** (`docling_markdown.py:200-226`, so each page decides its own OCR) | `application/convert.py` | At a few seconds a page on a CPU, 24,000 pages is a day or more for the first conversion | A process pool over documents. Measure before changing Docling's per-page call |
| 6 | **Sync is gentle with the web and not with Jira or Confluence.** Those two connectors have no `429` handling and build a new `httpx.Client` for each request (`jira.py:254`). Jira fetches an issue again for its attachments and again for each attachment (`jira.py:231-236`) | Folder sources re-read and re-hash every file on every sync, and the ledger commits row by row | About 25,000 sequential requests for 5,000 issues. A `429` is a failed fetch, so that item waits for the next sync (R2.23) instead of a short pause | One client per sync, the retry policy `domain/retries.py` already has for models, attachments from the listing, and one transaction per source |
| 7 | **Grounding normalises the whole document for every field, and again on every cache hit** (`domain/grounding.py`, `application/run.py:1120-1133`) | CPU-bound, so `--concurrency` does not help | Tens of full NFKC and regex passes per 60-page contract per step | Normalise once per document per step |
| 8 | **Traces hold the whole prompt** with `capture: full`: document and reference in each LLM span, the corpus in an `aggregate` trace. Eval flushes and posts feedback for each judged trace, synchronously | `application/extract.py`, `infrastructure/tracking/mlflow.py` | Megabyte traces, and around 15,000 traces from a run served wholly from cache | Cap or hash large payloads; flush once at the end. Check how the MLflow version in use bounds its async export queue |
| 9 | **Two files per unit per run under `runs/`**, written whether or not the answer was cached | `application/run.py` | About 30,000 files per run for 5,000 issues and 3 steps, until `gc` | Acceptable once `gc` runs on a schedule. Keep it in mind on Windows |

Smaller, and only at this scale:

- Quadratic bookkeeping: `_held` and `_members` in `execute`, and the
  per-batch scan in `embed`.
- The HNSW index exists before the first load, so it grows row by row
  (`infrastructure/index/postgres.py`).

None of these is visible at playground size, which is the point of §3.1.

### 3.3 Cost: prompt caching for reference documents

R3.18 shows every call reading `reference` every reference document, "paid for
once per audited document" (spec 003). The text is identical in every call
(R3.18 row 2). That is the case provider prompt caching exists for: Anthropic
bills a cache read well below the normal input price, and OpenAI applies
automatic prefix caching to a long repeated prefix. Check the current rates
before quoting a saving.

Today it cannot apply. `playground/17` puts `<procedures>{{reference}}</procedures>`
after the incident, so no two calls share a prefix. And no provider client asks
for caching: no `cache_control` appears in `src/`.

The shape:

- Prompt guidance (and the playground) puts `{{reference}}` first.
- The Anthropic client marks a cache breakpoint at the end of that prefix.
- R9.18's counts gain the cache-read tokens the providers already report.

It changes no answer and no key, since it is transport. It is still a spec
amendment to 009, because it changes what is sent. Of everything in this
document, it is the cheapest change with a measurable saving, and it weakens
the main argument for retrieval as a stage input (§2).

### 3.4 Operations: running it every day

Spec 015's flow is "cron (daily)". Four things stand between that and a team
relying on it.

- **No lock between commands.** Spec 016 says it plainly: "`gc` takes no lock.
  Run beside a `dossier run`, it can delete entries that run is writing." The
  same holds for two `sync`s, such as cron's and a person's, and for `embed`
  beside `run`. The shape is one workspace lock, taken by every command that
  writes (`sync`, `convert`, `run`, `embed`, `gc --apply`, `review apply`) and
  not by those that only read (`status`, `search`, `--plan`). See §5.2 for the
  library.
- **`dossier_version` never moves.** `pyproject.toml` has said `0.1.0` since the
  first commit, and there are no tags. Every provenance record, manifest and
  MLflow run carries that string. Converters and the chunker version
  themselves (R8.2, `HEADINGS_VERSION`); scoring and grounding do not. So an
  `eval` of one run, repeated months apart, can give two scores after a scoring
  change such as R6.17, and nothing recorded says why. Keys are right to leave
  the version out (R0.4). Provenance is where it belongs, and it should
  identify the code. Either bump the version on every behaviour-changing merge,
  or derive it from tags (§5.2).
- **No way to deploy it.** There is no image and no documented runner, and the
  whole workspace lives on one disk. `.dossier/snapshots` is the one part that
  cannot be derived again once a source has changed. For an audit tool, that
  is the evidence, so it needs a backup policy. The shape is a Dockerfile on
  `python:3.12-slim` (already the "second machine" for byte checks), a
  documented scheduled runner, and a backup note for `.dossier/snapshots` and
  `ledger.db`.
- **A stale environment fails confusingly.** Run for this review from the
  shared `.venv`, the suite failed R18.11: `no installed` provider for
  `ollama` embeddings. The venv predated the `dossier.embeddings` entry point.
  CI was green on the same commit. R10.17 already refuses an install that
  predates MLflow's auth provider. Generalising it, so that the CLI and
  `conftest.py` compare the entry points `pyproject.toml` declares with the
  installed ones and say "run `uv sync`", would end a trap this project has
  fallen into more than once.

### 3.5 Code health

A green suite does not cover these. I checked each one against the code.

**Correctness, worst first:**

1. **`gc` measures "held" with the wrong hash.** `cli/gc.py:133-141`
   `_held_snapshots` collects `row.content_hash`. Convert records carry
   `row.snapshot` (`application/convert.py:390`), and R16.3 keeps a conversion
   "if its snapshot is held now". For a source that declares `fields`, the two
   hashes differ (R2.17, `domain/ledger.py:41-50`). There, `gc --apply` deletes
   the conversions of documents the ledger still holds. No answer is lost
   (R5.9), but each one is converted again, which for Docling is the slow part.
   The code and the spec disagree here. Under CLAUDE.md that is reported, not
   fixed in passing, so it is a one-row amendment to R16.3 (a `fields` source)
   and a fix.
2. **A truncated reply is accepted, and cached.** No provider checks why a
   reply stopped. `openai_compatible.py` and `ollama.py` never read
   `finish_reason` or `done_reason`. `anthropic.py:99` reads `stop_reason` only
   when there is no text block, and its `MAX_TOKENS` is 16,000. A step with no
   schema (`application/extract.py:114-135`) accepts a reply cut off for length
   as its answer and caches it, and every later run is served it. A step with a
   schema spends its one retry (R6.2) on a correction that is about the wrong
   problem. An `aggregate` report over a few hundred documents is the likely
   victim. The shape: a stop for length is a `ModelRequestFailed`, never
   cached, in all three providers.
3. **One damaged manifest stops `run`, `--plan`, `eval`, `embed` and `status`.**
   `latest_manifest` (`application/plan.py:97-106`) parses every newer
   manifest, in any pipeline, before it checks which pipeline the manifest
   belongs to. Manifests are written with a plain `write_text`
   (`application/manifest.py:53`). A process killed mid-write, or a person
   editing `runs/` (which R0.11 allows), breaks every later command. Only `gc`
   tolerates it (R16.11). The shape: write manifests atomically, as
   `ArtifactCache` already does, and have one function list runs, tolerant
   where `gc` is.
4. **A damaged parts container drops a document from a run without a word.**
   `unpack_parts` raises `ValueError` both for "not a container" and for "a
   container cut short" (`domain/conversion.py:172-194`). `cli/run.py:468-471`
   catches both with `continue`, and so do `application/run.py` (about line
   1802) and `cli/calibrate.py` (about line 92). The document then holds no
   parts, and the `per_part` step skips it (`application/run.py:645-653`). It
   is not a failure, `failures.json` does not list it, and the run exits 0.
   Replay is loud about the same case. The shape: a domain `is_container` that
   checks the magic bytes, with a malformed container raising.
5. Smaller:
   - A judge call that raised still closes its trace with `status="OK"`
     (`application/eval.py`, the `finally` around line 788).
   - Model errors echo the endpoint URL verbatim (`infrastructure/models/_http.py`),
     onto the MLflow span even under `capture: hashes`. That only matters if
     someone puts a credential in a URL.

**Structure:**

- **About 700 lines of pure decisions sit in `application/run.py`, lines
  791-1557.** They cover which units and members a step covers, the skip
  chain, how inputs are rendered into a prompt, and what a cached result is
  re-grounded with. Mutation testing runs on `domain/` only (`mutation.toml`),
  so none of these is mutation-tested. Moving them is the "default to
  `domain/`" rule, not a refactor for its own sake.
- **Execute and replay compute the same things twice.**
  - The skip chain: `application/run.py:527-552` and `1886-1907`.
  - `StageInputs`: `916-947` and `2023-2057`. R4.14 records that this pair has
    already broken once.
  - Replay treats only `markdown` as text (`1890`, `2070`, `2183`), while
    `execute` takes any kind that decodes. Every shipped converter writes
    `markdown`, but a plugin converter writing another text kind (R8.7) would
    make a replay skip units its run asked about.
- **Other duplicates:**
  - Reproducing a run is written four times: `cli/run.py`, `cli/eval.py`,
    `application/embed.py` and `application/gc.py`.
  - "Which directories are runs" is written three times (`plan.py`, `gc.py`,
    `status.py`), each tolerating a different amount of damage.
  - Turning conversions into run inputs is written four times: `cli/run.py`
    (twice), `cli/calibrate.py` and `cli/embed.py`.
- **The largest functions:**

  | Function | Lines |
  |---|---|
  | `application/run.py` `execute` | 492 |
  | `cli/run.py` `_execute` | 322 |
  | `cli/eval.py` `eval_` | 258 |
  | `application/sync.py` `sync_source` | 237 |

  v1 asked for `cli/main.py` to be split, and it was. The weight moved into
  these.

None of this needs a refactoring project. The next feature that touches a run
should bring three things with it:

- a domain `skip_reason` that execute and replay share;
- an application `gather_run_inputs` that `run`, `calibrate` and `embed` share;
- one way to list runs.

### 3.6 Specs and docs that drifted

v1's drift (README's rule counts, the playground count, files at the root) is
fixed. The new drift comes from specs 015 to 019 landing faster than the older
prose around them was updated. These are the places a new contributor would
be misled first:

| Says | Where | What is true |
|---|---|---|
| Two documents with identical content share one stage key "(R5.5, R5.7 row 4)" | `application/run.py:1139-1143`, the comment on the cache-hit path | R5.10 superseded that row: no two documents share a stage key |
| "Not a search engine … searching it, clustering it and chatting over it are done by what reads it" | spec 000, Non-goals | `dossier search` exists (spec 019). The non-goal needs rewording, not deleting: dossier searches, and it does not serve search to others or chat |
| Search "is not part of `dossier`"; "`dossier search` is a later spec" | spec 018, lines 19-21 and 107 | Spec 019 built it |
| "`dossier.infrastructure.connectors` is the only place a network client may be imported" | spec 000, "The hash boundary"; the docstrings of `connectors/__init__.py` (R0.1), `models/__init__.py` (R0.9), `models/openai_compatible.py` and `tracking/__init__.py` ("three packages", "it only sends") | Four packages may (R0.17), and tracking reads back registry ids and verdicts |
| `review pull` "is the only command that reads MLflow back" | `README.md:380`, `docs/review-in-mlflow.md`, spec 011 ("reads nothing back (R0.10)") | `run` and `eval` look prompt versions up by hash (`application/prompts.py`), and `eval` looks datasets up. R0.17 allows both; R15.5 fences only reviewers' verdicts |
| "every command that opens a record takes" `--label` | spec 010, R10.11 row 3 (MET) | `gc` and `embed` open records and have no `--label`; they read the label from the environment only |
| The kinds of record, their default experiments and their variables | spec 010, the `{kind}` tables (about lines 31-207); spec 011's "What is recorded" | Both predate `gc`, `embed`, `search` and `status`, which the code records (`domain/tracking.py`) |
| The review loop is "**Not built** … What is missing is the file, and the reviewer's answers coming back" | spec 007, "The review loop"; spec 006 R6.5 row 2 | Reviewers' answers come back through `dossier review pull` and `review apply` (spec 015), and `apply_correction` has a caller (`application/review.py`) |
| "R0.10: exactly three packages may reach the network" | `README.md:426` | Four (R0.17) |
| "one of the two packages that may reach the network (R0.9)"; "(R0.10)"; "(R0.16)" | `pyproject.toml` comments | R0.17 |
| Rule ids that have been superseded | 74 citations in 42 files under `src/`: R0.10 32 times, then R1.2 (7), R0.1 (6) and R7.13 (6) | Some are history ("R0.1 said otherwise") and fine. Most cite a superseded rule as the reason for current behaviour |

Also stale, and less likely to mislead:

- **Layers that name functions which do not exist.**
  - `dossier.domain.grounding.check_source` (spec 006) is `check_field`.
  - `dossier.cli.eval._judge_gate` (spec 007) is `judge_gate`.
  - `dossier.domain.scoring.regressed` (spec 011) is `regressed_fields`.
- **R15.5 row 2 has no live rule behind it.** It rests on "R0.10 row 5", and
  R0.16 and R0.17 dropped that row, so no live rule says `Tracker` returns
  nothing.
- **Spec 000 is out of date in three places.**
  - Its workspace layout omits `tries/`, `review/` and `indexes/`, and the
    `judge` and `embed` caches.
  - R0.13's prose counts the modes as if `per_group` did not exist.
  - `specs/README.md` says "eight global invariants" where spec 000 says
    "these six".
- **`docs/architecture.md` lags the code.**
  - Its module list omits `gc`, `status`, `embed` and `search`.
  - It says `httpx` is imported at module scope, but the connectors import it
    lazily.
  - Its diagram lets `config` depend on `application`, which the layer test
    forbids.
- **The `live` marker covers more than the docs say.** `CLAUDE.md` and
  `README.md` describe it as "the evaluated rules, and Docling's models". It
  also runs the Chromium tests and the Postgres tests.
- **`playground/README.md` is behind.** It annotates `--help` with 5 commands
  of 12, and exercises 12 to 14 are in neither its offline list nor its
  exceptions.

An architecture test can keep the superseded-id citations from coming back.
It would fail a comment that cites a `SUPERSEDED` rule unless the same comment
names the rule that replaced it. The rest needs a `/verify` pass that reads
specs against each other, not only against code. No test reads prose, so the
cross-spec check is a job for a person or that skill.

---

## 4. What I would do next

In order. Sizes are S (a day or less), M (a few days) and L (a week or more).

| # | What | Why now | Size |
|---|---|---|---|
| 1 | **Harden for a real corpus.** In order: a refused request fails its document rather than the run, with `num_ctx` for Ollama (§3.2 rows 1-2); the four bugs in §3.5; page images loaded per document (§3.2 row 3); `embed` caching per batch (row 4); the workspace lock and a version that moves (§3.4); the entry-point check | These are what the pilot would trip over, and most change a spec, so each goes through `/discover` | M–L |
| 2 | **Pilot on the real incident corpus** (see below) | It answers every OPEN question, and it orders everything after it | M |
| 3 | **Prompt caching for reference documents** (§3.3) | The cheapest measurable saving | S |
| 4 | **Measure search.** A spec for relevance: gold queries, nDCG@10 and recall@100 against an exhaustive scan, computed in `domain/`, and an `evaluated` rule at a threshold the user agrees. An LLM relevance judge is admitted through the existing calibration gate | Answers spec 019 Q1 and Q2, and decides BM25 and reranking on numbers | M |
| 5 | **Office attachments** through Docling's DOCX, PPTX and XLSX backends | If the pilot's sync shows Office files left unconverted. Real Jira and Confluence attachments are full of them | S |
| 6 | **Cost estimate, `--max-cost`, then batch mode** | Once the pilot says what a run costs | M |
| 7 | **Prompt optimisation as a proposer** (§5.3) | Once `review pull` has grown gold to about 50 documents | M |
| 8 | **Drift cleanup** (§3.6), plus a check that a code comment citing a superseded rule also names its replacement | Cheap, and new contributors read these first | S |
| 9 | **Split `application/run.py`** (§3.5) | Only when it is next changed for a feature, not as its own project | M |

**The pilot, concretely.**

1. Sync the real Jira project (500 to 2,000 issues) and the Confluence space
   that holds its procedures.
2. Run the incident pipeline on the cheapest pinned model with
   `--concurrency 4`. Record wall time, tokens, memory, failures and the share
   of fields grounded.
3. Review 50 to 100 traces in MLflow, then `review pull` and `review apply`
   them into gold. Calibrate the `root_cause` judge on real cases (N ≥ 40).
4. `embed`, then write 30 questions people really ask. Judge the top 10 of
   each by hand: that is the first relevance gold set.
5. Write it up as `docs/pilot-2026-10.md`: the numbers, the answers to the
   OPEN questions, and this table re-ordered by what the pilot found.

**What I would not do next:** open a spec for a new capability before the
pilot reports (step 1's amendments are fixes, not capabilities), add more
MLflow surface, or add commands nobody has asked for yet.

**Deferred until a pilot or a user asks:** long documents (split, then gather),
nested records, near-match grounding, multimodal embeddings, clustering,
Confluence Cloud, websites behind a login, and retrieval as a stage input.
Row-level security is no longer on this list: #675 decided against Postgres
roles.

**On #675.** A search on people's behalf is the first consumer of `acl`. That
makes per-item permissions more pressing than this review assumed, because
Jira security levels and Confluence page restrictions are still "later work"
(spec 018). The pilot should check how many real issues carry a restriction
narrower than their project's. If it is many, a reader filter at the source
level answers the wrong question.

---

## 5. Frameworks, part by part

### 5.1 The test a framework has to pass here

The experience since v1 gives a sharper test than v1 had. A framework fits
dossier when:

1. it sits behind a port or entry point dossier already has;
2. what it produces can be pinned exactly and named in a key, as Docling's
   version and model weights are (R8.2, R8.28, R8.29); and
3. it never owns the model call, the schema, or anything read back into a key,
   a manifest or a score.

Docling passed all three and shipped byte-identical output across two
machines. LlamaIndex and Haystack failed the third: they bring their own
schema, embedding client and Postgres client. Spec 018 and spec 019 rejected
them for that reason, and I agree with both decisions.

### 5.2 Adopt now

| Part | Today | Adopt | Why it passes |
|---|---|---|---|
| **Object storage sources** (S3, GCS, Azure Blob, SFTP) | `folder` reads a local path | **fsspec** (BSD-3): a `folder` that takes a URL. An ETag or mtime is the remote version. dlt's filesystem source is fsspec underneath, plus a loader dossier does not need | Behind `dossier.connectors`. It only fetches bytes, and projection hashing and tombstones stay dossier's |
| **Office attachments** | No converter: the document fails on its own (R8.25), or is left out when mapped to `[]` (R8.27) | **Docling's DOCX, PPTX and XLSX backends.** They load no ML models; they read the file with a format library | Behind `dossier.converters`, pinned like `docling-markdown`. `docling-slim`'s Office extras import `pypdfium2` at module scope (docling issue #4283), so install them beside the PDF extra, as dossier already does |
| **A workspace lock** | None (spec 016) | **filelock** (Unlicense), or `msvcrt` and `fcntl` directly | Tiny, cross-platform, and decides nothing |
| **The version** | `0.1.0` since the first commit | **hatch-vcs**: the version comes from git tags, through the build backend already in use (hatchling) | Provenance identifies the code. An editable install still has to be reinstalled to see a new tag, so pair it with the entry-point check in §3.4 |

### 5.3 Adopt after measuring

| Part | Candidate | When | Notes, checked 2026-10-01 |
|---|---|---|---|
| **Keyword ranking** | **pg_textsearch** (Timescale; PostgreSQL licence; v1.4.0; PG 17 and 18) for BM25 instead of `ts_rank_cd` | When the relevance gold shows word-ranking ties cost recall | It needs `shared_preload_libraries`, so `dev/index` would need its own image on top of `pgvector/pgvector`. Phrase queries are post-filtered. Its corpus statistics count rows a reader cannot see, which matters for the per-reader search #675 opened. ParadeDB is still AGPL |
| **Reranking** | **Qwen3-Reranker served by vLLM**, through its Cohere-compatible `/v1/rerank` | When nDCG@10 says the fused list is the weak point | Ollama has no rerank endpoint. dossier already verifies what a vLLM serves (R9.4), so a reranker is one more pinned model, cached like a vector |
| **Prompt optimisation** | **GEPA** (`gepa-ai/gepa`), or `mlflow.genai.optimize_prompts` (MLflow ≥ 3.5, which wraps GEPA and DSPy) | When gold reaches about 50 documents | Use it as a **proposer**: its output is a prompt file in a PR, measured by `eval --compare` and the change gate. Prefer GEPA's own adapter with dossier's eval as the metric, so the model is still asked through dossier's clients and cache. MLflow's version calls the model through its own path |
| **Judge rubrics** | MLflow judge alignment (SIMBA, MemAlign) | With the item above | It proposes a rubric; dossier's calibration admits it (R7.5, R7.19) |
| **Retrieval metrics** | **ranx** or pytrec_eval | With §4 step 4 | As a test oracle only. nDCG and recall are a few lines in `domain/`, which is how the Wilson bound and kappa were decided (spec 007, "Existing options considered"). ranx brings numba |

### 5.4 Still no

| Framework | Why not |
|---|---|
| LangChain, LlamaIndex, Haystack (ingestion, retrievers, vector stores) | Their own schema, embedding client and Postgres client sit outside dossier's keys and network boundary (spec 018, spec 019) |
| LiteLLM | It would hide the provider. dossier verifies what is actually served: an Ollama digest, a vLLM repository (R9.4, R9.6) |
| Instructor, PydanticAI, BAML, Outlines | All three provider clients already use native structured outputs (`response_format`, `output_config`, Ollama's `format`), and the schema comes from the YAML declaration (R6.10) |
| Dagster, Prefect, Airflow | Steps are a linear list over documents with a keyed cache. A scheduler adds a server to run one cron line |
| Ragas, DeepEval, promptfoo | They report unvalidated judge scores. The gate that withholds them is dossier's product |
| Label Studio, Argilla | The review loop was built on MLflow (spec 015) |
| CocoIndex, pgai | They keep an index fresh, and cannot say which snapshot or run produced a row. pgai has had no release in a year (spec 018) |
| DVC, lakeFS | The snapshot store is about 235 lines (`infrastructure/store.py` and `domain/store.py`) and already content-addressed |

---

## 6. Decisions that are the user's

- **The pilot's corpus**: which Jira project and Confluence space, how many
  issues, and which models may see them. A cloud model means real incident
  text leaves the network, so that is a data-governance call before it is a
  technical one.
- **Prices and a default for `--max-cost`.** dossier should not invent either.
- **A version policy**: bump on behaviour changes, or tags with hatch-vcs.
- **Relevance thresholds** for an `evaluated` search rule, once the numbers are seen.
- **New dependencies**: fsspec, filelock, hatch-vcs, and a custom index image
  for pg_textsearch. Each is a commit message with a reason (CLAUDE.md).
- **Retrieval as a stage input**: whether it is ever in scope (spec 000's
  non-goals).

---

## Sources

- pg_textsearch: [GitHub](https://github.com/timescale/pg_textsearch), [v1.0 announcement](https://www.postgresql.org/about/news/pg_textsearch-v10-3264), [Tiger Data blog](https://www.tigerdata.com/blog/pg-textsearch-bm25-full-text-search-postgres)
- vLLM rerank and Qwen3-Reranker: [vLLM scoring](https://docs.vllm.ai/en/latest/models/pooling_models/scoring/), [Qwen3 Reranker on vLLM](https://docs.vllm.ai/projects/ascend/en/latest/tutorials/models/Qwen3_reranker.html); no rerank endpoint in Ollama: [ollama#16076](https://github.com/ollama/ollama/issues/16076)
- Prompt optimisation: [MLflow optimize prompts](https://mlflow.org/docs/latest/genai/prompt-registry/optimize-prompts/), [GEPA](https://github.com/gepa-ai/gepa)
- Docling Office formats: [supported formats](https://docling-project.github.io/docling/usage/supported_formats/), [docling#4283](https://github.com/docling-project/docling/issues/4283), [docling-slim on PyPI](https://pypi.org/project/docling-slim/)
- dlt filesystem source: [dlt docs](https://dlthub.com/docs/dlt-ecosystem/verified-sources/filesystem)
- ranx: [GitHub](https://github.com/AmenRa/ranx)
