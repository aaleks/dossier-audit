# 018 — The embedding index

**Status:** Implemented
**Rules:** R18.1 – R18.11

## Purpose

What `dossier` holds is searchable today only by the categories a run extracts.
A question such as "which incidents failed the way `INC-4830` did" has no
category to filter on, and the words of a document are not indexed at all.
`dossier embed INDEX` writes the documents of a pipeline's sources into a
PostgreSQL index twice over: as vectors, to be searched by meaning, and as
text, to be searched by words. A run's categories come along as values to
filter on, and its free-text answers as one more chunk to search.

The index is derived data. Everything in it is rebuilt from the workspace: the
snapshots, their conversions, the runs and a cache of vectors. Postgres is
never the source of truth, and a second `dossier embed` with nothing changed
asks no model and writes nothing. Search, clustering and chat read the index;
they are not part of `dossier` (spec 000's non-goals). `dossier search` is a
later spec.

## The declaration

An index is declared in its own file, so changing it changes neither the
pipeline's hash nor its version (spec 013):

```yaml
# indexes/incidents.yaml
pipeline: incident-audit
embedding_model: ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
chunker: {name: headings, max_chars: 2000}
fields:
  filter: [failure_category, component, root_cause_category, contributing_factor_category, architecture_category]
  embed: [root_cause]
target: {dsn_env: DOSSIER_INDEX_DSN}
```

- **`pipeline`** names the documents (its sources) and the run output (its
  latest run's scored step, R16.2) the index is built from. The answers are the
  run's as `dossier eval` reads them: reproduced from its manifest and the cache
  (R4.7, R7.10), its manifest pinning the snapshot each document was read at.
  They are never read from the copies under `runs/`, which are for people and
  may be edited without any later command noticing (R0.11): the index and
  `eval` read one run the same way.
- **`embedding_model`** is pinned exactly, as a pipeline's model is (R0.6). An
  Ollama tag is pinned by digest (R9.3); the digest above is the registry's for
  `qwen3-embedding:4b-fp16` on 2026-10-01.
- **`chunker`** names a registered chunker and its settings. `headings` is the
  first.
- **`fields`** names the fields of the pipeline's output declaration the index
  carries: categories to filter on, free text to embed.
- **`target`** names the environment variable holding the connection string.
  Credentials come from the environment (R1.8).

Every source the index reads declares who may read it, in `sources.yaml`:

```yaml
sources:
  - id: incidents-jira
    type: jira
    acl: [incident-response]
```

## What it writes

Two tables, in a schema `dossier` creates and owns (`dossier_index`):

| Table | Columns |
|---|---|
| `documents` | `index`, `document_id` (`<source>:<key>`), `source_id`, `key`, `title`, `snapshot`, `acl`, `embedding_model`, `content_hash` (the hash of everything written for the document, compared to write only what changed, R18.4), `run_id`, and `filter_values`: the carried values as JSON |
| `chunks` | `index`, `chunk_id`, `document_id`, `kind` (`body` or `record`), `chunk_index`, `heading_path`, `text`, `text_search` (a `tsvector` of the heading path and `text`, as embedded, configuration `simple`; R19.9), `embedding`, `acl` |

One `chunks` table holds every index, so its vector column has one type, fixed by
the first index written: two indexes pinning models of different lengths need
two databases (R18.5).

`text_search` uses `simple`: no stemming and no stop words, because incidents
are written in more than one language and a stemmer for the wrong one mangles
words. Matching by meaning is the vectors' job. `embedding` is `halfvec(2560)`
for Qwen3-Embedding-4B, under an HNSW index by cosine distance (R18.5).

A document's **body chunks** are its converted text, cut at its headings
(R18.1). Its **record chunk** is the free-text answers its latest run gave,
rendered as `field: value` lines (R18.9). A category is never embedded: it is
exact, and a vector would only blur it.

## Decisions

Decided by `a.aleks` on 2026-10-01:

- A thin layer, owned by `dossier`, behind two ports: an `EmbeddingProvider` and
  a `Chunker` (see "Existing options considered").
- The first embedding provider is Ollama, and the first model
  `qwen3-embedding:4b-fp16`: 2,560 dimensions, 8 GB of weights. On this
  machine it runs on the CPU. The first full build of an index is the slow
  part, and is best run with little else open. After it, only changed chunks
  are embedded (R18.3).
- Postgres with pgvector, in a container defined in `dev/`, as the Jira and
  Confluence used for live checks are. Another system reads the index through
  views, and nothing but `dossier` writes it.
- Only a value the run grounded in the document is carried (R18.9).
- Readers are declared per source. Per-item permissions are later work.
- Full text with the `simple` configuration.
- A chunk is at most 2,000 characters, about 400 to 500 tokens. Characters, so
  no tokenizer is a dependency.
- The index only. `dossier search` and clustering are later specs.

## Existing options considered

Checked on PyPI on 2026-10-01:

| Option | Covers | What it leaves to `dossier` |
|---|---|---|
| LlamaIndex (`llama-index-core` 0.14.25, 2026-09-21; `llama-index-vector-stores-postgres` 0.9.0, 2026-08-31) | Markdown splitting with header paths, an ingestion pipeline with dedupe, a Postgres vector store with hybrid search | Its schema is one table with metadata as JSON, not these two. Its embedding and Postgres clients sit outside `dossier`'s cache keys and network boundary. The run-output link, staleness and snapshot-based incrementality are still `dossier`'s. A large dependency tree |
| Haystack (`haystack-ai` 3.2.0, 2026-09-24; `pgvector-haystack` 7.0.0, 2026-09-29) | A splitter, embedders, a pgvector store with vector and keyword retrieval | The same, somewhat lighter |
| pgai Vectorizer (0.12.1, 2025-10-13) | Embedding inside Postgres | No release for a year. Rejected |
| `psycopg` 3 (3.3.6, 2026-09-18) and `pgvector` (0.5.0, 2026-07-06) | The driver and the vector type | Chunking, the embedding call, the schema and the writes. **Chosen** |

Every part that makes this `dossier`'s is the part the frameworks leave to it:
the cache keys, snapshot incrementality, the run-output link, staleness, the
network boundary and the schema. What they cover, cutting text, asking for a
vector and writing a row, is small next to what `dossier` already has.

Chunking: Docling's chunkers take a `DoclingDocument`, which a Jira issue and a
Confluence page never become here. Chonkie (1.7.0) returns no heading path.
`semchunk` (4.1.1) cuts oversized text well, and is a dependency the `domain/`
layer may not import. The `headings` chunker is therefore a pure decision in
`domain/`, using the standard library. The `Chunker` port leaves room for
`semchunk` or LlamaIndex's `MarkdownNodeParser` as another chunker, registered
by entry point as converters are. Its name, version and settings are part of
every chunk's identity, so a change of chunker re-chunks rather than mixing
(R18.2).

## Left out on purpose

- **Search, clustering and chat.** The index is built for them, by other tools
  first and `dossier search` (spec 019). Qwen3-Embedding expects a query
  to carry an instruction prefix and a document not to. That is the search
  side's concern; documents are embedded as they are.
- **Per-item permissions.** Jira security levels and Confluence page
  restrictions would be a spec 001 change to every connector. The `acl` column
  holds a source's declared readers until then, and would hold per-item
  readers without changing shape.
- **A URL for a Jira issue or a Confluence page.** It needs each connector's
  base address and a rule of its own.
- **The container: a Jira project, a Confluence space.** Each connector knows
  it, and the core may not name it (R1.7): it needs a connector-declared field
  and a rule of its own. A source's documents are filtered by `source_id` until
  then.
- **When a document was synced.** The ledger's `last_seen` moves at every sync,
  so writing it would rewrite every row each time. `snapshot` says which content
  a row holds, and moves only when the content does.

## Open questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | How long does the first build of the playground corpus take with `qwen3-embedding:4b-fp16` on this machine's CPU? | RESOLVED on 2026-10-01: 76 s for the four playground notes, 21 chunks, the model's load included, with 7.7 GB of RAM free and no GPU. The second `embed` took 1 s: 0 embedded, 21 cached, 0 written |

## Must hold

The rules land in two slices. R18.7 closes the first: documents to vectors to
Postgres, with R18.1 to R18.6, R18.10 and R0.16. R18.11 closes the second: a
run's record, with R18.8, R18.9 and R11.33.

### R18.1 — a document is cut into chunks at its headings, and each chunk carries the headings above it

A section longer than the chunker's `max_chars` is cut at paragraph breaks, and
a paragraph longer than it at a sentence's end, then at a space. Every piece
keeps its section's heading path.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.chunks.heading_chunks`), behind the `Chunker` port (`dossier.domain.ports`)
- **Proved by:** `tests/unit/test_R018_1__a_document_is_cut_at_its_headings.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821`'s note, opening `# INC-4821 — Card payments declined at checkout`, with `## Impact` and `## Comments` beneath | the chunk holding `CHF 48'200` has the heading path `["INC-4821 — Card payments declined at checkout", "Impact"]` |
| 2 | a section of 5,200 characters in four paragraphs, `max_chars: 2000` | cut at paragraph breaks into pieces of at most 2,000 characters, each with the section's heading path |
| 3 | *counter-example* — one paragraph of 2,600 characters | cut inside it, at a sentence's end, then at a space; no piece is longer than 2,000 |
| 4 | *counter-example* — `audit-note.pdf`'s text, with no heading at all | one heading path, `[]`; the document's title is its key |
| 5 | *counter-example* — `handover-note.md`, zero bytes | no chunk |
| 6 | two paragraphs of 999 characters in one section, `max_chars: 2000` | one piece of exactly 2,000 characters, the two joined by a blank line: packed to the limit, not short of it |
| 7 | *counter-example* — paragraphs of 999 and 1,000 characters | two pieces: joined, they would be 2,001 characters, one past the limit |

### R18.2 — a chunk's id is the hash of its document, its chunker and settings, its position and its text

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.chunks.chunk_id`)
- **Proved by:** `tests/unit/test_R018_2__a_chunk_id_is_its_content.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` at `a3f9c1e2`, cut on Windows and in `python:3.12-slim` | the same ids, byte for byte (R0.4) |
| 2 | `INC-4821` re-synced with only its last comment changed | every chunk before the last keeps its id |
| 3 | *counter-example* — `max_chars` changed from 2,000 to 1,000 | every id changes: a chunk cut under other settings is another chunk (R0.5) |
| 4 | *counter-example* — one sentence in both `INC-4821` and `INC-4822` | two ids: a chunk belongs to its document |

### R18.3 — a chunk is embedded only when the cache holds no vector for the pinned model and the text it embeds

The text embedded is the chunk's heading path, then its text, so the chunk
holding `CHF 48'200` is found as `INC-4821`'s impact. The vector is cached
under the model and that text, as a stage's answer is cached under its inputs
(R5.5), and its key is the same on every machine (R0.4). The texts missing a
vector are asked for in requests of at most 32. A cached vector that cannot be
read is a miss, as any cache entry is (R5.9).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.embed`), domain (`dossier.domain.keys.embedding_key`)
- **Proved by:** `tests/unit/test_R018_3__a_chunk_is_embedded_only_on_a_cache_miss.py`, `tests/unit/test_R018_3__ollama_embeddings_request.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a second `dossier embed incidents`, nothing synced since | 0 embedding calls |
| 2 | `INC-4821`'s last comment changed and re-synced | 1 embedding call, for that chunk |
| 3 | *counter-example* — the embedding model's digest changed in `indexes/incidents.yaml` | every chunk embedded again: vectors from two models are not comparable |
| 4 | *counter-example* — one chunk text in two indexes pinning the same model | 1 embedding call: the vector is the model's answer to the text, whichever index files it |

### R18.4 — the index holds exactly the active documents of its pipeline's sources, and writes only what changed

- **Kind:** deterministic
- **Layer:** application (`dossier.application.embed`), domain (`dossier.domain.index.changes`), infrastructure (`dossier.infrastructure.index`)
- **Proved by:** `tests/unit/test_R018_4__the_index_holds_the_active_documents.py`, `tests/integration/test_R018_4__postgres_index_sink.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a second `dossier embed incidents`, nothing changed | `0 written · 0 removed` |
| 2 | `INC-4822` re-synced with new content | its document row and its chunks replaced; every other row untouched |
| 3 | `handover-note.md` tombstoned (R2.7) | its document row and its chunks deleted; `1 removed` |
| 4 | *counter-example* — `81920114.pdf` owed: its fetch failed at the last sync (R2.23) | its rows from the last embed kept: the ledger still holds it |
| 5 | *counter-example* — the index's tables emptied by hand | every row written again, from the cache, with 0 embedding calls: the index is derived data |
| 6 | *counter-example* — `INC-4822`, held, failing to convert at this `embed` (R8.6) | its rows from the last embed kept, and named: `INC-4822: not converted, its rows are kept: <the reason>`; `0 removed`. Removed, one converter's failure would take a held document out of search without a word |

### R18.5 — the vector column's type follows the length of the model's vectors

pgvector indexes a `vector` of up to 2,000 dimensions and a `halfvec` of up to
4,000. A vector of another length than the index holds is refused, not written.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.index.vector_column`)
- **Proved by:** `tests/unit/test_R018_5__the_vector_column_follows_the_model.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `qwen3-embedding:4b-fp16`, 2,560 values a vector | `halfvec(2560)`, under an HNSW index by cosine distance |
| 2 | 2,000 values | `vector(2000)` |
| 3 | 2,001 values | `halfvec(2001)` |
| 6 | `bge-m3`, 1,024 values | `vector(1024)`: full precision wherever pgvector can index it |
| 7 | 4,000 values | `halfvec(4000)`, at `halfvec`'s limit |
| 4 | *counter-example* — 4,001 values | refused: no pgvector type indexes it |
| 5 | *counter-example* — one chunk answered with 1,024 values, the others with 2,560 | refused, naming that chunk and both lengths; nothing of that `embed` is written, and none of its vectors cached |

### R18.6 — every row carries the readers its source declares, and a source declaring none is not indexed

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load.load_index`), domain (`dossier.domain.index`)
- **Proved by:** `tests/unit/test_R018_6__every_row_carries_its_sources_readers.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira` declaring `acl: [incident-response]` | every `INC-*` document row and chunk row holds `{incident-response}` |
| 2 | *counter-example* — `procedures-confluence`, read by the index, declaring no `acl` | refused at load, naming the source and the key to add; nothing written |
| 3 | *counter-example* — `incidents-manual` declaring `acl: []` | refused when `sources.yaml` loads, whether or not an index reads it: an empty list names no reader, and is not a decision about who may read it |

### R18.7 — `dossier embed INDEX` builds the index from what was synced

The outer loop of the first slice.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.embed`)
- **Proved by:** `tests/acceptance/test_R018_7__embed_builds_the_index_from_what_was_synced.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync incident-audit`, then `dossier embed incidents` | a document row for each active document and its chunk rows with their vectors; `incidents · N chunks · N embedded · 0 cached · N written · 0 removed`, every count but `written` and `removed` in chunks; exit 0 |
| 2 | then `dossier embed incidents` again | `0 embedded · N cached · 0 written · 0 removed`; 0 embedding calls |
| 3 | *counter-example* — `DOSSIER_INDEX_DSN` not set | exit 2, naming the variable, before any embedding call |

### R18.8 — a document's record comes from the pipeline's latest run, and only when that run read the snapshot the ledger holds now

A run's answers describe the snapshot it read. Attached to a newer one, they
would describe text that is no longer there.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.index.record_for`), application (`dossier.application.embed.read_latest_run`)
- **Proved by:** `tests/unit/test_R018_8__a_record_comes_from_the_run_that_read_the_held_snapshot.py`, `tests/unit/test_R018_8__embed_reads_a_run_as_eval_does.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `20260925T091500Z-5e6f` read `INC-4830` at the snapshot the ledger holds | its record carried, its document row naming `20260925T091500Z-5e6f` |
| 2 | *counter-example* — `INC-4830` re-synced since, at a new snapshot | indexed with no record; `INC-4830: record stale: 20260925T091500Z-5e6f read an earlier snapshot` |
| 3 | *counter-example* — the latest run failed `INC-4822` at `extract` (R4.27) | indexed with no record; `INC-4822: no record: failed at extract in 20260925T091500Z-5e6f` |
| 4 | *counter-example* — `incident-audit` has no run | every document indexed with no record; `no run of incident-audit yet` |
| 5 | *counter-example* — `INC-4901` synced after the latest run | indexed with no record; `INC-4901: no record: 20260925T091500Z-5e6f did not read it` |
| 6 | *counter-example* — the latest run read `INC-4901`, failed nothing, and filed no answer for it | indexed with no record; `INC-4901: no record: 20260925T091500Z-5e6f filed no answer for it` |
| 7 | *counter-example* — the latest run cannot be replayed: `extract`'s entry for `INC-4821` deleted from the cache | every document indexed with no record; once, `no record: 20260925T091500Z-5e6f cannot be replayed: ` and the replay's own error |
| 8 | *counter-example* — a reviewer edited `runs/20260925T091500Z-5e6f/extract/INC-4821.json`, its `severity` changed to `minor` | `major` carried, as the cache holds it and `eval` scores it: the copy is for people, and is never read back (R0.11) |

### R18.9 — a filter field is carried only when the run grounded it, and a text field is embedded in the document's record chunk

A value whose span is not in the document is scored incorrect whatever it says
(R7.4). Carried, it would let a filter return a category the document does not
support.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.index.carried`)
- **Proved by:** `tests/unit/test_R018_9__only_grounded_values_are_carried.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4830`'s `failure_category: certificate-expiry`, grounded | `failure_category: certificate-expiry` among its document row's values |
| 2 | `INC-4830`'s `root_cause`, grounded: `Certificate renewal and certificate deployment were two separate processes, and only the first was automated.` | a chunk of kind `record` whose text holds `root_cause: Certificate renewal and certificate deployment were two separate processes, and only the first was automated.` |
| 3 | *counter-example* — `component: payments-api`, whose span is not in `INC-4830` | not carried; `INC-4830: 1 value left out: ungrounded` |
| 4 | *counter-example* — `root_cause_category` abstained: `null`, with a reason | no value: the document does not state one |
| 5 | `INC-4830`'s `failure_category` answered `Certificate-Expiry`, grounded, where the declaration writes `certificate-expiry` | carried as `certificate-expiry`, the declared spelling: the check let it through folded (R6.26), and a filter on the declared value must find what `eval` scored correct |

### R18.10 — an index declaration is refused at load when a field is undeclared, a filter is free text, an embedded field is a category, or the model is not pinned

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load.load_index`)
- **Proved by:** `tests/unit/test_R018_10__an_index_declaration_is_checked_at_load.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `filter: [failure_categroy]` | refused, naming `failure_categroy` and the fields `schemas/incident.yaml` declares |
| 2 | `filter: [root_cause]`, a `free_text` field | refused: free text is embedded, not filtered |
| 3 | `embed: [severity]`, an `enum` field | refused: a category is filtered, not embedded |
| 4 | `embedding_model: ollama:qwen3-embedding:4b-fp16` | refused as R9.3 refuses an Ollama tag with no digest |
| 5 | *counter-example* — `indexes/incidents.yaml` as this spec writes it | loads |
| 6 | `fields` declared over a pipeline in which `extract` and `verify` both declare an output | refused, as `dossier eval` refuses it: an index carries the answers of one output (R17.6 row 5) |
| 7 | `embedding_model: openai:text-embedding-3-small`, and no installed package embedding for `openai` | refused, naming `openai` and the providers that do embed: a chat provider is not one that answers with vectors |
| 8 | `fields` declared over a pipeline in which no step declares an output | refused: `0 steps of incident-audit declare an output`, as `eval` refuses it |
| 9 | `chunker: {name: headings, max_chars: 0}` | refused at load: a piece of at most no characters holds nothing |

### R18.11 — what `dossier embed` carries of a run is the latest run's grounded record of the snapshot it holds

The outer loop of the second slice.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.embed`)
- **Proved by:** `tests/acceptance/test_R018_11__embed_carries_the_runs_record.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier sync`, `dossier run incident-audit`, `dossier embed incidents` | `INC-4830`'s document row holds its grounded categories and the run's id; it has a `record` chunk with its `root_cause`; exit 0 |
| 2 | then `INC-4830` changed, re-synced, and `dossier embed incidents` | its record removed and named stale; of its body chunks, only those whose text changed are embedded |
| 3 | *counter-example* — then `dossier run incident-audit` and `dossier embed incidents` | its record back, naming the new run |
