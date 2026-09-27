# dossier — an outside review

> Written 2026-09-23 against `main` at `f7d0ac2`. This is an opinion document, not
> a spec. Nothing here is a rule. Anything worth building goes through `/discover`.

## TL;DR

- **The core is strong and unusual.** The hash boundary, content-addressed
  snapshots, keyed caching with replay, grounding that affects the score, abstention
  that counts as an answer, and a judge that is *refused* when uncalibrated are real
  differentiators. Few open-source tools offer all of them together.
- **The edges are thin.** Model calls run one at a time, a 429 is not retried, no
  token or cost is recorded anywhere, there is no review loop, no list-valued or
  boolean fields, no grouping of files into one document, no OCR, and one model per
  pipeline. Those limits show up the first time someone runs 400 contracts.
- **The effort has leaned toward MLflow.** Specs 010–014 hold about 50 of the 205
  rules (~24%). They are careful and correct, but in the same period the
  product-level gaps listed in `docs/second-use-case.md` and the review loop in
  spec 007 stayed open.
- **Could frameworks have done it?** About 70–80% of the *functional* surface,
  yes: dlt, Docling, DocETL or LangExtract, and promptfoo or MLflow GenAI eval,
  connected with glue code. The *reproducibility and defensibility contract* would
  not come for free, and for an audit tool that contract is the product. Building
  the core was the right call. The recommendation is to **adopt components at the
  edges** (conversion, connector breadth, review UI) instead of building them.
- **Embeddings (`dossier embed`) fit well**, as long as they are a *write-only
  export* like MLflow and not a retrieval input. There is a concrete design in §6.
  Retrieval that feeds back into a stage is a separate and much bigger decision
  (§6.7).

---

## 1. What dossier is, in one paragraph

A batch tool for **defensible structured extraction from documents**. It syncs
sources into an immutable, content-addressed store, converts them (text and page
images), runs a linear pipeline of prompt stages with schema-validated output, and
checks that every extracted value cites a span that actually occurs in the
document. It scores the result per field against human-verified gold, with LLM
judges that must be calibrated against humans before their numbers are shown. Every
artifact is keyed by everything that produced it, so a six-month-old run can be
replayed byte for byte with no model call.

Size today: ~15.3k lines of Python in `src/`, ~43k lines of tests in 262 files,
~6.8k lines of spec, 205 rules, 464 commits between 2026-08-23 and 2026-09-22.

---

## 2. What is genuinely good

| Strength | Why it matters | Where |
|---|---|---|
| **The hash boundary as an architectural test** | Most "reproducible LLM pipeline" claims are aspirations. Here an `ast` walk fails the build when a network client is imported outside three packages, including lazily. | `tests/architecture/test_R000_10__…` |
| **Cache key = everything that can change an output** | Prompt, declaration, *generated* schema (R6.12), model pin, converter version, per-part keys (R4.14). A cache hit is a real promise. | `domain/keys.py` |
| **Replay with zero model calls, all-or-nothing** | Answers an auditor's question: "show me that this report came from these inputs." | R0.12, R4.7 |
| **Grounding affects the score** | An ungrounded value that matches gold is still scored wrong (R7.4). Most eval stacks would count it as a pass. | `domain/grounding.py`, R7.4 |
| **Abstention is an answer** | "Not stated" with a reason, scored correct against a gold null (R7.3). This removes the incentive to hallucinate. | R6.5, R7.3 |
| **The `described` state** | An honest third state for evidence in a chart, instead of forcing it into pass or fail. | R6.15, R7.20–R7.24 |
| **Judge governance** | Calibration against humans, staleness when the rubric *or the wrapper* changes (R7.19), per-state bars, and **withholding** the metric instead of printing it. MLflow, promptfoo, DeepEval and Ragas will all happily report an unvalidated judge score. | `domain/judges.py`, R7.13–R7.23 |
| **Pinned and verified models** | Floating aliases refused (R0.6). A vLLM serving another repo, or an Ollama tag re-pulled to another digest, stops the run (R9.4, R9.6). | `domain/model_id.py` |
| **Pipelines are data** | YAML declarations instead of pydantic modules (R6.10), so opening someone else's pipeline runs nothing. This matters for audit and for supply-chain safety. | spec 006 |
| **"A fake is a claim, verify it live"** | The project found four MLflow bugs that were green in the suite, and wrote the lesson down. That is a mature habit. | CLAUDE.md, memory |
| **The playground** | Twelve exercises against a stub model server that uses the real code path. An excellent onboarding asset. | `playground/` |

---

## 3. Concerns — engineering and process

### 3.1 The process costs a lot, and it shows in *what* got built

The spec-first, rule-per-invariant loop produces very high confidence per rule. The
cost is that everything is expensive, so priority matters a great deal. In the
last month:

- Specs 010–014 (MLflow runs, records, datasets, logged models, prompts) took about
  50 rules.
- Meanwhile, the product findings in `docs/second-use-case.md` are still open:
  **no grouping** ("a master plus N amendments is one document"), **no boolean or
  duration kind**, and the review loop in spec 007 is marked "Not built".

MLflow is a projection of what dossier already knows. The review loop and grouping
change what dossier *can do*. The suggestion is to weight the next month toward
§4 below.

### 3.2 Documentation drift in the files people read first

- `README.md` says "165 rules across 12 specs … 156 MET". `CLAUDE.md` says 205
  across 15, with 194 MET.
- `playground/README.md` says "Eleven hands-on exercises" and then lists twelve.
- `KICKOFF.md` is the prompt for the *first* session (R2.5). It is history now and
  could move to `docs/history/`.
- `jira_connector.md` and `brainstorming_images_pdf/` sit at the root and are
  tracked. They are working notes, not project docs.

A small test that compares README's stats line with the counts
`test_spec_coverage.py` already computes would stop the first kind of drift for
good.

### 3.3 `CLAUDE.md` has turned into a changelog

It is ~30 KB, and most of it is the narrative of each slice ("A picture is
judged…", "A run leaves something to open…"). That text is loaded into **every**
agent session. It costs tokens, and it buries the working agreement (rules,
loops, constraints) under history. Recommendation: keep `CLAUDE.md` to the
agreement, the constraints and the architecture (~4–5 KB). Move the narrative to
`docs/changelog.md` or to short ADRs. The "why" is valuable and should be kept,
just not in the always-loaded file.

### 3.4 The composition root has grown too large

- `src/dossier/cli/main.py` is 2,038 lines. `_execute` is ~260 lines, and
  `_compare_runs`, `_judging`, `_held_content` and `_reproduced` hold real
  orchestration. The quality report (#3, #6, #7, #27) already flagged decisions
  that live in `cli/`. Suggestion: one module per command (`cli/run.py`,
  `cli/eval.py`, …) and a `bootstrap.py` that builds clients, stores and trackers.
- `application/run.py:184` `execute()` takes **25 keyword arguments**. A frozen
  `RunInputs` / `RunServices` pair would make the call sites readable, and would
  make it harder to forget a new argument (the `prompt_prefix` / `versions` /
  `prompt_registry` additions show the pattern).

### 3.5 CI is not committed

`.github/workflows/ci.yml` exists locally but is untracked. Until it is merged, "the
suite is green" means only "the last person to run it saw green". Given how much
of the project's value rests on the suite, this is the cheapest high-value change
available.

---

## 4. Usage — what would make dossier better to *use*

Ordered by how soon a real user would hit each one.

### 4.1 Throughput: calls are sequential and a 429 kills the call

- No concurrency anywhere in `src/` (no threads, no async). A per-file step over 400
  documents × 3 steps is 1,200 calls made one after another, each with a 300 s
  timeout (`models/_http.py:21`).
- `_http.request` turns *any* non-2xx into `ModelRequestFailed`, so a rate limit or
  a transient 503 fails that document.

**Suggestion.** Run in parallel *within* a step and keep a barrier *between* steps.
The cache-keyed design makes this safe: each (step, document) is independent, and
the only ordering that matters is how the manifest and report are written, which
already sort. Add `--concurrency N` (and a per-provider default), plus
transport-level retry with backoff on 429/5xx. Keep that retry clearly separate
from R6.2's single *validation* retry, which is about content and not transport.

**Bigger win for backfills:** provider **batch APIs** (OpenAI Batch, Anthropic
Message Batches) cost about half as much and suit a keyed cache well. `dossier run
--batch` would submit every cache miss of a step, return, and fill the cache when
the batch completes. The run becomes resumable by construction.

### 4.2 Cost is not recorded anywhere

No token usage is captured (`grep` finds no `usage` or `input_tokens` in `src/`).
For a tool whose selling point is "a new audit in an afternoon", the first question
from a manager is "what did it cost?".

- Record `input_tokens`, `output_tokens` and latency in the provenance record
  (never in the key, like `attempts` in quality-report #15) and as MLflow metrics.
- `dossier run --plan` could *estimate* the cost of the misses it already counts.
- `--max-cost` as a hard stop.

### 4.3 One model per pipeline

`PipelineConfig.model` is pipeline-wide (`domain/pipeline.py:128`). The common
real pattern is a cheap model for `extract` and a strong one for `verify` or
`report`. A per-step `model:` override that falls back to the pipeline default
would cost almost nothing, because the model is already in every key.

### 4.4 The document model: the second use case still does not fit

The findings in `docs/second-use-case.md` are still true:

| Gap | Example | Suggested shape |
|---|---|---|
| Several files are one document | a master contract plus amendments; a Jira issue plus its PDF | `group_by:` on the source, `mode: per_group` |
| Long documents | a 60-page contract in one `per_file` call | `split` then `gather` (DocETL's pattern): process chunks with neighbouring context, then reduce |
| Multi-valued fields | `affected_systems` is really a list | `kind: list` of a kind, scored with precision and recall |
| More kinds | `auto_renew`, `notice_period_days` | `boolean`, `number`, `duration` (90 days equal to 3 months) |
| Nested records | a list of liability caps, each with an amount and a scope | objects in the declaration |

### 4.5 The review loop — the biggest missing product feature

Spec 007 already designs it: `review.jsonl`, reviewer verdicts, and corrections
merged into gold through `apply_correction` (which has no caller). All the data
exists: value, span, derived page, grounding state and `detail`.

A cheap, high-impact version: `dossier review <run_id>` writes a **static HTML page
per run**. Each document's text has each field's span highlighted and the page
number shown, with accept, reject and correct controls that export a corrections
file for `dossier gold apply`. LangExtract's HTML visualisation shows how much a
reviewer gains from seeing spans in context. If a server-side tool is acceptable,
**Argilla** or **Label Studio** already provide annotation queues.

This also answers "where does the gold set come from?". Reviewing is labelling.

### 4.6 Conversion quality: OCR and tables

`pdf-markdown` reads only the text layer. A scanned PDF (the contract case) has no
text, so every field can at best be `described` and never `grounded`. Tables come
out flattened.

**Suggestion:** a `docling-markdown` converter shipped as a separate package on the
`dossier.converters` entry point (so the "converters are plugins" design is used
as intended). Docling does layout, tables and OCR, and keeps page and bbox
provenance per element. Pin its version and its model weights in the converter
version (R8.2). It is MIT-licensed, which avoids the AGPL problem that ruled out
PyMuPDF.

### 4.7 Span matching may be stricter than intended

`locate_span` normalises whitespace only (`domain/grounding.py:41`). PDF text layers
often contain ligatures (`ﬁ`), soft hyphens across line breaks, and curly quotes.
Models tend to "correct" these when quoting, so an honest citation can become
`ungrounded`. Suggestions, both through a spec change because they change scores:

- NFKC, de-hyphenation and quote folding, applied to both sides (as whitespace
  normalisation already is);
- optionally a separate **near-match** state (LangExtract uses fuzzy alignment),
  so it is reported and never silently counted as grounded.

### 4.8 Judge statistics

The gate compares a point estimate: `calibration.agreement >= threshold`
(`domain/judges.py:96`), with N ≥ 20. CLAUDE.md already notes that 20/20 at N=20
has a lower bound near 84%. Three cheap improvements:

1. **Gate on the Wilson lower bound**, or at least print it.
2. **Report Cohen's κ.** With 60% of the sample "supported", a judge that always
   says "supported" gets 0.60 agreement but κ = 0.
3. **Report sensitivity and specificity separately.** R7.12 (the planted claim) is
   a specificity check with n = 1. Catching unsupported claims is the whole job,
   so it deserves its own number and its own bar.

### 4.9 Small ergonomic commands

| Command | What |
|---|---|
| `dossier init` | scaffold `sources.yaml`, one pipeline, one declaration, `.env.example` |
| `dossier status` | what is held per source, last sync, last run, calibration state per judged field |
| `dossier run --doc KEY` / `--sample N` | iterate on a prompt against one document without a full run |
| `dossier diff <run_a> <run_b>` | per-*document* value changes, the detail behind `--compare`'s per-field delta |
| `dossier gc --keep-runs …` | the stage cache is content-addressed and grows without limit; prune what no kept manifest reaches (snapshots stay immutable, R0.2) |

### 4.10 Prompt optimisation against the gold set

The project already has the three things a prompt optimiser needs: a gold set, a
deterministic scorer, and a change gate. **DSPy** (GEPA, MIPROv2) or MLflow's prompt
optimisation could *propose* a better `01_extract.md`. The result is a file in a
PR, measured through `eval --compare` like any other edit, so nothing is read back
from a registry and R12.4 and R14.5 stay intact. MLflow's **judge alignment**
(`make_judge` plus `align()` with SIMBA or MemAlign) could likewise propose a
better rubric, which must then be recalibrated through dossier's own gate.

---

## 5. Could this have been built on frameworks? Alternatives and combinations

### 5.1 Capability by capability

| Capability | dossier's own | Could have used | Verdict |
|---|---|---|---|
| Connectors, incremental sync, deletions | `connectors/`, `ledger.py`, `domain/sync.py` | **dlt** (verified Jira and filesystem sources, incremental cursors, merge dispositions), Airbyte, LlamaHub readers, Unstructured ingest | **Keep the core.** Projection hashing, revisions and "complete listing" tombstones are specific to dossier. For *breadth* (Confluence, SharePoint, GDrive, S3), a generic connector that wraps dlt sources is cheaper than writing each one. |
| Immutable snapshots | `store.py` (85 lines) | DVC, lakeFS, git-annex, Pachyderm | Keep. It is small, and the others add infrastructure for no gain here. |
| Conversion | 6 converters | **Docling**, MarkItDown, Marker, Unstructured | **Adopt as plugins** (§4.6). This is the largest quality gain available. |
| Pipeline DSL + per-document cached steps | `domain/pipeline.py`, `keys.py`, `run.py` | **DocETL** (YAML, map/reduce/resolve/split/gather), DVC pipelines, Dagster assets, Hamilton caching, Prefect cache keys, Flyte, Snakemake | Keep. DVC and Dagster cache per stage or file, not per (step, document, part) with a cascade. **Borrow DocETL's operators** for grouping and long documents. |
| Structured output + one retry | `extract.py` | Instructor, PydanticAI, BAML, Outlines | Keep. The own code is small and schema generation is tied to the YAML declaration. |
| Grounding | `domain/grounding.py` | **LangExtract** (character offsets, fuzzy alignment, chunked multi-pass, HTML review) | Borrow ideas: fuzzy alignment as a separate state, and the review visualisation. |
| Gold, scorers, judges, calibration | `domain/scoring.py`, `judges.py`, `eval.py` | MLflow GenAI (`make_judge`, `align`, datasets, assessments), **promptfoo**, Inspect AI, DeepEval, Ragas, Langfuse, Braintrust | **Keep the gate.** It is the moat. Use MLflow alignment to *improve* a rubric, and dossier's calibration to *admit* it. |
| Human review | not built | **Argilla**, Label Studio, Langfuse annotation queues | Adopt, or build the static HTML page (§4.5). |
| Tracking | MLflow via a port | MLflow | Already done, and done carefully. |

### 5.2 Combinations that would reach most of the target

**A. The data-engineering stack** — dlt → object store (versioned with lakeFS or
DVC) → Docling → DocETL, or LangExtract per document → promptfoo or MLflow GenAI
eval → Argilla for review.

- *Gets:* broad connectors, strong conversion, parallelism, grouping and long
  documents, a review UI, and reports. Probably 1–2k lines of glue.
- *Misses:* per-(step, document) keys with a cascade, `--plan`, zero-call replay,
  pinned *and verified* model serving, grounding that affects the score,
  abstention scoring, and the calibrated-judge gate. Each would have to be written,
  and together they are most of dossier's domain layer.

**B. Incremental AI indexing** — **CocoIndex** (sources, incremental lineage,
`ExtractByLlm`, pgvector target) plus MLflow eval.

- *Gets:* incremental reprocessing, extraction, and **embeddings into pgvector out
  of the box** (§6). This is the closest single tool to "sync + extract + embed".
- *Misses:* grounding, abstention, judge governance, replay and the audit trail.
  CocoIndex keeps targets fresh; it does not prove how an old answer was produced.

**C. Managed platforms** — Unstructured Platform or LlamaCloud (LlamaParse plus
LlamaExtract with citations), with Langfuse or Braintrust for evaluation.

- *Gets:* the fastest demo, good parsing, citations, hosted UIs.
- *Misses:* reproducibility guarantees, pinned models, on-premises operation
  (documents leave the network), and cost control. It also means vendor lock-in
  for an audit trail that should outlive the vendor.

### 5.3 Is there one project that already does all of this?

Not that I know of. The closest neighbours each cover one axis:

| Project | Covers | Lacks |
|---|---|---|
| DocETL | declarative YAML pipelines over documents, map/reduce/resolve, optimiser | grounding gate, gold scoring with calibrated judges, snapshot/ledger sync |
| LangExtract | grounded extraction with offsets, HTML review | sync, pipelines, gold scoring, judges |
| CocoIndex | incremental sync and transform, vector targets | grounding, eval, replay |
| promptfoo / Inspect AI | eval, change gate, model comparison | ingestion, grounding, per-document cache |
| Unstract | prompt studio for document extraction, connectors | reproducibility contract, judge governance |

**Conclusion.** dossier sits in the intersection that none of these covers:
*extraction whose every number is defensible and reproducible*. Rebuilding that
intersection was justified. Rebuilding the edges (converters, connector breadth, a
review UI) is not. Adopt those through the entry points the design already has.

---

## 6. Feature proposal — `dossier embed` (pgvector)

### 6.1 First, the non-goal

Spec 000 says: *"Not a search or retrieval-augmented chat system."* An embedding
**export** does not break that. Dossier does not *serve* search; it publishes an
index for systems that do. That is the same stance as MLflow: a write-only
projection that nothing reads back (R10.4, R12.4). Suggested amendment to the
non-goal:

> dossier does not serve search or chat. It may **export** what it holds (documents
> and findings) as embeddings for systems that do, and nothing it exports is read
> back.

### 6.2 Two things worth embedding

| What | Unit | Why someone wants it |
|---|---|---|
| **Source documents** (`dossier embed <pipeline>`) | chunks of each converted document (`markdown`; `page_images` later) | a RAG or search system over the same frozen corpus the audit read, with the snapshot hash on every row so answers can cite *the audited version* |
| **Run findings** (`dossier embed <pipeline> --run <run_id>`) | one row per field record: value, span, page, grounding state | semantic search across audits ("root causes like this one"), near-duplicate incidents, clustering root causes, choosing diverse documents to label next |

The second is the more original. No other tool has *grounded, scored findings*
to embed.

### 6.3 How it fits the architecture

```
domain/chunking.py            pure: (converted bytes, chunker config) -> chunks with ids,
                              char offsets and the page read off anchors (as R6.14 does)
domain/ports.py               + Embedder   (embed(texts) -> vectors; a model call)
                              + VectorSink (upsert(rows), retire(ids); write-only, like Tracker)
application/embed.py          the use case: plan, cache lookup, embed misses, upsert, retire
infrastructure/models/*       + embed(): OpenAI-compatible /v1/embeddings, Ollama /api/embed,
                                Gemini via its OpenAI-compatible route; Anthropic has none
                                (a `voyage` provider would cover that)
infrastructure/sinks/         pgvector.py (psycopg + pgvector); entry point group dossier.sinks
config/                       DOSSIER_PGVECTOR_DSN, named and never written (as R1.8 does)
cli/                          dossier embed
pyproject                     extra: dossier[pgvector]
```

The **hash boundary gains a fourth package** (`infrastructure/sinks`). R0.10
would be superseded in place by a new R0 rule, as R0.9 was, and the `ast` test
extended to count `psycopg` as a network client.

### 6.4 Determinism: where it holds and where it cannot

- **Chunk ids are content-addressed**:
  `sha256(snapshot hash ‖ kind ‖ chunker@version ‖ char_start ‖ char_end)`. They are
  byte-identical across machines, so re-embedding an unchanged corpus produces
  identical ids and the upserts do nothing.
- **Embedding vectors are not bit-reproducible.** Providers change float results
  across hardware and batches. As with stage answers, **the cache is what makes it
  reproducible**. Key it on (embed model, dimensions, chunker version, chunk text
  hash), store the vector bytes in `.dossier/cache/embed/`, and ask the provider
  only on a miss. `--plan` asks nothing.
- **The embedding model is pinned** by the same rules as `model:` (R0.6). Each
  provider's pinned form has to be stated when it is added.
- **Nothing read from Postgres enters a key, a manifest or a score.** ANN
  (HNSW) results are approximate and non-deterministic, which is one more reason
  the sink must stay write-only.

### 6.5 Configuration sketch

```yaml
# pipelines/incident-audit/pipeline.yaml
embed:
  model: openai:text-embedding-3-large      # pinned, same rules as `model:`
  dimensions: 1536                          # enters the key; see pgvector limits below
  chunker: {by: headings, max_tokens: 512, overlap: 64}
  documents: [markdown]                     # which kinds to embed
  findings: [verify]                        # which steps' field records to embed
  sink: pgvector                            # an entry point in `dossier.sinks`
```

```
dossier embed incident-audit --plan          # chunks to embed, cached, to retire
dossier embed incident-audit                 # source documents, incrementally
dossier embed incident-audit --run <run_id>  # that run's findings
```

### 6.6 pgvector schema sketch

```sql
create extension if not exists vector;

-- one table per (embed model, dimensions): a vector column has a fixed width
create table dossier_chunks__te3l_1536 (
  chunk_id     text primary key,          -- content-addressed, 64 hex
  source_id    text not null,
  item_key     text not null,             -- INC-4821
  snapshot     text not null,             -- the audited version, 64 hex
  kind         text not null,             -- markdown | page_images
  page         int,                       -- derived from anchors, never guessed
  char_start   int not null,
  char_end     int not null,
  content      text not null,
  chunker      text not null,             -- headings@1.0.0
  embed_model  text not null,
  state        text not null default 'active',   -- mirrors the ledger (tombstoned)
  dossier_version text not null,
  embedding    halfvec(1536) not null
);
create index on dossier_chunks__te3l_1536 using hnsw (embedding halfvec_cosine_ops);

create table dossier_findings__te3l_1536 (
  finding_id   text primary key,          -- sha256(stage key ‖ field)
  run_id       text not null,
  pipeline     text not null,
  version_hash text not null,             -- spec 013's pipeline version
  step         text not null,
  document     text not null,
  field        text not null,
  value        jsonb,
  span         text,
  page         int,
  grounding    text not null,             -- grounded | ungrounded | described | abstained
  embedding    halfvec(1536) not null
);
```

pgvector's HNSW index accepts up to 2,000 dimensions for `vector` and 4,000 for
`halfvec`. `text-embedding-3-large` at 3,072 therefore needs `halfvec` or a reduced
`dimensions`, and the chosen width must be part of the key.

### 6.7 Candidate rules for `/discover` (not numbered, not agreed)

1. Chunking is a pure function in `domain/`. Chunk ids are byte-identical across
   machines, timezones and hash seeds.
2. The embedding model is pinned, and a floating alias is refused at load time.
3. An embedding is cached under a key over model, dimensions, chunker version and
   chunk text. The provider is asked only on a miss, and `--plan` asks nothing.
4. A second `dossier embed` with nothing changed sends zero embedding requests and
   writes zero rows (the twin of R2.5).
5. A tombstoned item's chunks are retired from the sink by the next `embed`
   (the twin of R2.20).
6. The sink is write-only. Nothing it holds enters a key, a manifest or a score
   (the twin of R10.4 and R12.4).
7. `dossier embed` refuses when the sink cannot be reached, because the export is
   its whole output (the twin of R12.5). A `run` that also exports never fails
   because the sink is down (the twin of R13.5).
8. The DSN is named in configuration and never written there (the twin of R1.8).
9. Every row carries its snapshot hash, chunker version, embed model and
   `dossier_version`.
10. `embed` opens an MLflow record of its own kind with its counts (spec 011
    style).

### 6.8 The bigger decision: retrieval as an *input* to a stage

Where embeddings would really change dossier is large `reference` corpora. Today
every procedure is put into the prompt whole. Retrieving the relevant chunks is the
obvious next step, and it **crosses the non-goal and the hash boundary**. If it is
ever done:

- retrieve **locally**, from the embedding cache, with **exact** cosine search and
  ties broken by chunk id, never through pgvector's ANN index;
- make the retrieval result (the ordered chunk ids) a cached artifact under a key.
  Replay then reads the ids and never searches again;
- treat it as its own spec with its own decision record, not as part of the export.

**Recommendation:** ship the export (§6.1–6.7) first. It is low-risk, useful on its
own, and fits the existing patterns exactly. Keep retrieval as an open question.

### 6.9 Alternatives to building the sink

- **pgvector** (requested): SQL joins with metadata, and most teams already run
  Postgres. A good default.
- **LanceDB**: embedded and file-based, so it could live beside `.dossier/` with no
  server. A good local option behind the same `VectorSink` port.
- **Qdrant or Weaviate**: if a team already runs one.
- **CocoIndex**: if the *only* goal were "keep a pgvector index fresh from these
  folders", it does that incrementally out of the box. It would not know about
  snapshots, findings or grounding, so it is the wrong tool for the findings index.
- **Multimodal later:** `page_images` could be embedded with a multimodal or
  late-interaction model (ColPali or ColQwen style) for chart-heavy corpora. This
  pairs naturally with the `described` state.

---

## 7. Suggested order of work

| # | Item | Why now | Size |
|---|---|---|---|
| 1 | Commit CI; fix README and playground counts; slim `CLAUDE.md` | cheap, protects everything else | S |
| 2 | Concurrency within a step, 429/5xx backoff, token and cost in provenance | the first thing a real-scale run hits | M |
| 3 | Review loop: static HTML review page, then corrections into gold | biggest product value; the data already exists | M |
| 4 | `docling-markdown` converter plugin; span normalisation (NFKC, hyphens) | scanned PDFs become groundable | M |
| 5 | Document model: `list`, `boolean`, `number` kinds; `per_group`; per-step `model:` | the second use case becomes possible | L |
| 6 | `dossier embed` export to pgvector (documents, then findings) | the requested feature; fits the patterns | M |
| 7 | Judge statistics: Wilson bound, κ, sensitivity and specificity | makes the gate harder to fool | S |
| 8 | Batch-API mode; `dossier status`, `init`, `gc`, `run --doc` | quality of life, cost | M |
| 9 | Split `cli/main.py`; a `RunInputs` object for `execute()` | maintainability | M |
| — | Retrieval as a stage input | a decision, not a task | — |

---

## Sources

- DocETL — [paper](https://arxiv.org/abs/2410.12189), [docetl.org](https://www.docetl.org/llms.txt), [blog](https://data-people-group.github.io/blogs/2024/09/24/docetl/)
- LangExtract — [GitHub](https://github.com/google/langextract), [Google Developers Blog](https://developers.googleblog.com/introducing-langextract-a-gemini-powered-information-extraction-library/)
- CocoIndex — [incremental processing](https://cocoindex.io/blogs/tags/incremental-processing/), [academic papers example](https://cocoindex.io/docs/examples/academic_papers_index)
- Docling — [chunking](https://docling-project.github.io/docling/concepts/chunking/), [hybrid chunking](https://docling-project.github.io/docling/examples/hybrid_chunking/)
- MLflow judge alignment — [alignment](https://mlflow.org/docs/latest/genai/eval-monitor/scorers/llm-judge/alignment/), [SIMBA](https://mlflow.org/docs/latest/genai/eval-monitor/scorers/llm-judge/simba/), [`make_judge`](https://mlflow.org/docs/latest/api_reference/_modules/mlflow/genai/judges/make_judge.html)
- pgvector limits — [issue #461](https://github.com/pgvector/pgvector/issues/461), [Neon docs](https://neon.com/docs/extensions/pgvector), [Supabase HNSW](https://supabase.com/docs/guides/ai/vector-indexes/hnsw-indexes)
