# 019 — Searching the index

**Status:** Partially implemented
**Rules:** R19.1 – R19.12

## Purpose

`dossier embed` writes an index that can be searched by meaning and by words
(spec 018). Nothing in `dossier` can search it yet, so the only way to find the
incidents that failed the way `INC-4830` did is to write SQL against
`dossier_index`. `dossier search INDEX QUERY` asks the index a question in
plain words and lists the documents that answer it, best first. It ranks them
by meaning and by words together, filters them by the values a run grounded,
and limits them to what a reader may read. The ranking is a pure decision over
two ranked lists, so the order is provable without a database. The query is a
model's input like any other, embedded only on a cache miss.

## The command

```
dossier search incidents "certificate expired at checkout" --as incident-response
dossier search incidents "certificate expired at checkout" --as incident-response --where component=checkout
dossier search incidents "alert routed to an archived channel" --as incident-response --as sre --limit 5
dossier search incidents "certificate expired at checkout" --all-readers --chunks --json
```

| Option | Default | Does |
|---|---|---|
| `--as READER` | none; it or `--all-readers` is required | keeps the chunks one of the named readers may read; repeatable (R19.10, R19.11) |
| `--all-readers` | off | searches every chunk, whoever may read it, and says so (R19.11) |
| `--limit N` | 10 | how many documents, or chunks with `--chunks`, are listed |
| `--where FIELD=VALUE` | none | keeps the documents carrying that value; repeatable (R19.4) |
| `--chunks` | off | lists chunks rather than documents (R19.2) |
| `--json` | off | prints the same results as JSON (R19.12) |

It changes nothing: it writes no file, no row and no cache entry but the
query's vector (R19.3).

## How a search ranks

The query is asked twice of one index, inside one transaction:

- **By meaning:** the chunks nearest the query's vector, by cosine distance,
  through the HNSW index (R18.5).
- **By words:** the chunks whose `text_search` matches
  `websearch_to_tsquery('simple', QUERY)`, ranked by `ts_rank_cd`. `simple`,
  as the index was written (spec 018). A chunk's words are its heading path
  and its text, the text its vector was made from (R19.9).

Each list holds at most 100 chunks, after the filters. The two are fused by
**reciprocal rank fusion**: a chunk's score is the sum, over the lists it is
in, of `1 / (60 + rank)`. A chunk is ranked by where it stands in each list,
not by its distance or its text rank, which are on scales that cannot be
added. A chunk found only by words still ranks: an incident key or an error
code is found by words, and is near nothing in meaning (R19.1).

A document is listed at its best chunk's place, once. `--chunks` lists the
fused chunks as they are, so one long runbook can fill the list, which is why
documents are the default (R19.2).

**Filters on a vector index.** pgvector applies a `WHERE` after the HNSW scan.
Without more, a filter matching one chunk in ten returns about four of the
forty the scan reads. Searches set `hnsw.iterative_scan = relaxed_order`
(pgvector 0.8.0 and later; `dev/index` runs 0.8.6), so the scan goes on until
the list is full or the index is exhausted (R19.4 row 7). It matters only when
the planner reads the HNSW index: under a selective filter, or on an index of a
few thousand chunks, Postgres reads every chunk the filter keeps and sorts them
exactly, which fills the list without it. Ties in either list are ordered by
chunk id under the `C` collation, as Python orders them, whatever the
database's own collation: `en_US` ignores a hyphen, and would cut a list at a
different chunk than R19.1 ranks.

**A filter matches a whole value.** A carried value is one string, or a list
of strings when the run answered several (R18.9). `--where` matches one of
them whole: `affected_systems`, a `reference`, holds one string per document,
such as `checkout-api, payments-gateway`, and `--where
affected_systems=checkout-api` does not match it. A field meant to be filtered
on each of its parts is declared a `list`.

**Words, all of them.** `websearch_to_tsquery` matches a chunk holding every
word of the query, as a web search does, and `simple` drops none: `certificate
expired at checkout` matches only a chunk holding `at` too. A question in plain
words often matches no chunk by words, and is ranked by meaning alone (R19.8
row 3). `or` between words widens it, as its syntax allows. Whether any word
should do is open question 2.

## The query instruction

Qwen3-Embedding is trained with an instruction on the query and none on the
document. Its model card puts the cost of leaving it out at 1% to 5% of
retrieval quality. The instruction is declared in the index file, because it
says what the corpus is:

```yaml
# indexes/incidents.yaml, beside spec 018's fields
query_instruction: >-
  Given a question about incidents, retrieve the passages of incident records
  and documents that answer it
```

Without the field, it is the default above. The text embedded is
`Instruct: <instruction>`, a newline, and `Query:<query>`, the model card's
format. An instruction declared empty embeds the query as it is typed, for a
model trained without one. The documents are embedded as they always were
(spec 018).

## Decisions

Decided by `a.aleks` on 2026-10-01:

- Native SQL, with reciprocal rank fusion at the constant 60, over the index
  spec 018 writes. Not ParadeDB or LlamaIndex (see "Existing options
  considered").
- `--as READER` is optional. Without it, the output says the search was not
  filtered by reader: whoever holds the DSN can read every row anyway.
  Enforcement in the database is a later spec.
- One MLflow trace per search, with an EMBEDDING span and a RETRIEVER span, and
  no MLflow run (R11.34, in spec 011).
- Documents by default, each at its best chunk; `--chunks` for chunks.
- `query_instruction:` declared per index, with the default above.
- Text, and `--json`.

Decided by `a.aleks` on 2026-10-01, after the rest was built, for an agent that
will search on people's behalf:

- Readers are kept apart by the application holding the connection, as `--as`
  does, and never by Postgres: where `dossier` runs, a role per reader cannot
  be managed. Whoever holds the connection string reads every row ("Left out
  on purpose").
- A search names the readers it is for, or asks for every chunk with
  `--all-readers` (R19.11). Before, a search with no `--as` listed every chunk,
  and an agent that forgot the flag would have shown someone everything.
- `--as` is repeatable, and keeps what any of the readers named may read, in
  one ranked list (R19.10): a person often reads as more than one.

## Reading back from the index

Spec 018 fenced what `dossier` reads from the index to the ids and content
hashes of the rows it holds, so it writes only what changed. A search reads
back what the index is for: chunks, their text, their documents' titles and
values, and their ranks. It does so through its own port, `IndexSearch`, so
`IndexSink` still reads back only ids and hashes. Nothing a search reads
enters a key, a manifest or a score. It reaches the terminal and MLflow, and
nothing else. R0.17 says so, superseding R0.16.

## Existing options considered

| Option | What it covers | Delta |
|---|---|---|
| Postgres full text and pgvector, fused in SQL by reciprocal rank (pgvector's README, "Hybrid search") | Both rankings, the filters, the readers, on the image `dev/index` already runs | Nothing to install. `ts_rank_cd` is not BM25 |
| ParadeDB `pg_search` (v0.25.11, 2026-09-29; AGPL-3.0; about 9.3k stars) | BM25 ranking inside Postgres | Its own image, replacing `dev/index`'s; AGPL; another extension to pin. Better keyword ranking than `ts_rank_cd`, for the half of the fusion words already do well enough |
| LlamaIndex `PGVectorStore` hybrid and `QueryFusionRetriever` (`llama-index-core` 0.14.25) | Fusion, rerankers | Expects its own one-table schema, not spec 018's. Its clients sit outside the cache keys and the network boundary: rejected for spec 018 for the same reasons |

Decision: the first. A search is one query of the schema `dossier` owns, and the
decisions it adds, fusion and grouping, are pure and belong in `domain/`.

## Left out on purpose

- **Enforcing readers in the database.** Decided against ("Decisions"). A
  role per reader needs roles managed where `dossier` runs, and a session
  setting the policies read is set by whoever holds the connection, so it
  enforces nothing. Measured on `dev/index`, 30,000 chunks: under row-level
  security the vector index still serves the list by meaning, and the words
  list loses its GIN index, because `@@` is not leakproof and Postgres will not
  apply it before the policy. Every search by words then read every row, 6.5
  ms here, in proportion to the table.
- **Reranking.** A cross-encoder over the fused list is pgvector's other
  suggestion. It is a second model per search, and nothing yet measures
  whether it helps.
- **Measuring relevance.** Whether the ranking finds the right incidents is a
  judgement, an evaluated rule with gold queries: a later spec, once a real
  corpus is indexed.

## Open questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | Is 100 candidates per list enough, on a real corpus, for `--limit 10` documents? | OPEN: needs the user's incident corpus indexed, and the recall of 100 against an exhaustive scan measured once |
| 2 | Should the words list match a chunk holding any word of the query, rather than all? | OPEN: any word finds more, and ranks the noise of short words with it; needs queries a person asked of a real corpus, judged both ways |

## Must hold

### R19.1 — chunks are ranked by reciprocal rank fusion of their ranks by meaning and by words

A chunk's score is the sum, over the two lists it is in, of `1 / (60 + rank)`,
its rank counted from 1. Higher scores first. Two equal scores are ordered by
chunk id, so a search lists the same order on every machine.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.fused`)
- **Proved by:** `tests/unit/test_R019_1__chunks_are_ranked_by_reciprocal_rank_fusion.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4830`'s root-cause chunk 1st by meaning and 2nd by words; `INC-4977`'s body 2nd by meaning only; `INC-4901`'s 1st by words only | `INC-4830`'s first, at `1/61 + 1/62`; then `INC-4901`'s, at `1/61`; then `INC-4977`'s, at `1/62`: found both ways outweighs leading one way |
| 2 | the query `INC-4830`: its chunks 1st and 2nd by words, and nowhere in the first 100 by meaning | both ranked, at `1/61` and `1/62`: an incident key is found by words, and is near nothing in meaning |
| 3 | two chunks, one only 1st by meaning and one only 1st by words | equal scores, `1/61`; the one whose chunk id sorts first, first |
| 4 | *counter-example* — a chunk in neither list | not ranked at all; a fusion gives no chunk a score of 0 |
| 5 | one chunk 1st by meaning and 4th by words, another 4th by meaning and 1st by words, as `warehouse or cost` ranked two of exercise 05's notes | both at `1/61 + 1/64`, to the last digit; the one whose chunk id sorts first, first |

### R19.2 — a search lists documents, each once, at its best chunk's place; `--chunks` lists the chunks

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.listed`)
- **Proved by:** `tests/unit/test_R019_2__a_document_is_listed_once_at_its_best_chunk.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | fused: `INC-4830`'s root cause 1st, `INC-4977`'s body 2nd, `INC-4830`'s record chunk 3rd | `INC-4830`, shown at its root-cause chunk, then `INC-4977`: two documents |
| 2 | the same, `--limit 1` | `INC-4830` alone |
| 3 | the same, `--chunks` | the three chunks, in that order, `INC-4830` twice |
| 4 | *counter-example* — fused: `INC-4830`'s root cause 1st, its record chunk 2nd, `INC-4977`'s body 3rd; `--chunks --limit 2` | `INC-4830`'s two chunks, and `INC-4977` not listed: chunks are not grouped, so one document can fill the list |

### R19.3 — the query is embedded with the index's model, after the declared instruction, and only on a cache miss

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.query_text`), application (`dossier.application.search`)
- **Proved by:** `tests/unit/test_R019_3__the_query_is_embedded_after_its_instruction.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `certificate expired at checkout`, no `query_instruction:` | the text embedded is `Instruct: Given a question about incidents, retrieve the passages of incident records and documents that answer it`, a newline, and `Query:certificate expired at checkout`; one embedding call |
| 2 | `query_instruction: Find the runbook that says what to do` | that instruction, in place of the default |
| 3 | the same search again | 0 embedding calls: the vector is cached in the `embed` namespace, keyed by the model and that text (R18.3) |
| 4 | *counter-example* — `query_instruction: ""` | the text embedded is `certificate expired at checkout`, as typed |

### R19.4 — `--where FIELD=VALUE` keeps only the documents carrying that value, and a field or value the index does not carry is refused

The value is read as the declaration spells it, so a filter finds what `embed`
carried (R18.9 row 5). A refusal comes before the model is asked.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.wheres`), infrastructure (`dossier.infrastructure.index.postgres`)
- **Proved by:** `tests/unit/test_R019_4__where_keeps_the_documents_carrying_a_value.py`, `tests/integration/test_R019_4__postgres_search_filters.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `--where failure_category=certificate-expiry` | `INC-4830`, and no document that does not carry `certificate-expiry` |
| 2 | `--where component=CHECKOUT` | the same as `component=checkout`: read in the declared spelling |
| 3 | `--where failure_category=certificate-expiry --where component=checkout` | the documents carrying both |
| 4 | `--where component=checkout --where component=payments-api` | the documents carrying either: one field given twice is one choice of values |
| 5 | `--where root_cause=certificate` | exit 2, `root_cause is not a filter of incidents; its filters are architecture_category, component, contributing_factor_category, failure_category, root_cause_category`; 0 embedding calls |
| 6 | `--where failure_category=meteor-strike` | exit 2, naming the field and its declared values; 0 embedding calls |
| 7 | a live index of 400 documents, 10 carrying `failure_category=certificate-expiry` and farthest from the query; the planner reading the HNSW index; `--limit 10` | 10 documents: the scan goes on past its first 40 chunks until the list is full. With `hnsw.iterative_scan = off`, fewer |
| 8 | *counter-example* — no `--where` | every document the reader may read is considered |
| 9 | *counter-example* — `--where checkout`, `--where component=` or `--where =checkout` | exit 2, `--where takes FIELD=VALUE; got component=`, naming what was given; 0 embedding calls |

### R19.5 — `--as READER` keeps only the chunks that reader may read, and a search without it says it is not filtered

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.reader_refusal`), infrastructure (`dossier.infrastructure.index.postgres`)
- **Proved by:** `tests/unit/test_R019_5__as_reader_keeps_what_the_reader_may_read.py`, `tests/integration/test_R019_4__postgres_search_filters.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira` declaring `[incident-response]`, `procedures-confluence` declaring `[sre]`; `--as incident-response` | `incidents-jira`'s documents only; the first line says `as incident-response` |
| 2 | the same, `--as sre` | `procedures-confluence`'s documents only |
| 3 | the same, no `--as` | both sources' documents; the first line says `not filtered by reader` |
| 4 | *counter-example* — `--as incident-responce` | exit 2, `no source of incident-audit declares incident-responce as a reader; they declare incident-response, sre`; 0 embedding calls. A typo would otherwise find nothing and look like an answer |

### R19.6 — a search of an index holding nothing, or embedded with another model than its declaration's, is refused before the model is asked

A query vector from one model is meaningless against another's, and the
lengths need not even agree.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.model_refusal`)
- **Proved by:** `tests/unit/test_R019_6__a_search_refuses_an_index_of_another_model.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `indexes/incidents.yaml`'s `embedding_model` changed since the last `dossier embed incidents` | exit 2, `incidents was embedded with <held>, and is declared with <declared>: run dossier embed incidents`; 0 embedding calls |
| 2 | no `dossier embed incidents` yet | exit 2, `incidents holds nothing yet: run dossier embed incidents`; 0 embedding calls |
| 3 | *counter-example* — embedded with the declared model | searched |

### R19.7 — a search names how many held documents the index does not hold as they are held

A search answers from what was last embedded. A document synced since, changed
since, or tombstoned since is invisible or out of date in it, and nothing in a
ranked list says so.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.unreflected`)
- **Proved by:** `tests/unit/test_R019_7__a_search_names_what_the_index_does_not_reflect.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4901` synced after the last `dossier embed incidents` | `1 held document not in incidents as held: run dossier embed incidents`, after the results |
| 2 | `INC-4822` re-synced at a new snapshot since | the same count, 1 |
| 3 | `INC-4821` tombstoned since, its rows still in the index | the same count, 1 |
| 4 | *counter-example* — nothing synced since the last embed | no such line |

### R19.8 — `dossier search INDEX QUERY` prints the documents that answer it, best first

The slice's acceptance rule, through the CLI, with the embedding model and the
index as fakes, as R18.7's are.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.search`), domain (`dossier.domain.search.excerpt`)
- **Proved by:** `tests/acceptance/test_R019_8__search_lists_what_answers_the_query.py`, `tests/unit/test_R019_8__a_result_shows_its_text_on_one_line.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | R18.11's workspace, synced, run and embedded; `dossier search incidents "certificate expired at checkout"` | the first line, `incidents · 1 document · not filtered by reader`; then `1. INC-4830`, its title, the heading path of its best chunk, its text on one line cut at a word to at most 200 characters, and its carried values; exit 0 |
| 2 | the same, `--json` | one JSON object: `index`, `query`, `reader`, and `results`, each with `rank`, `document_id`, `title`, `values`, the chunk's `heading_path`, `kind` and `text`, and its `score`; nothing else on stdout |
| 3 | *counter-example* — `dossier search incidents "kubernetes"`, which no chunk matches by words, and only far chunks by meaning | the documents by meaning still listed: a fusion of one list is that list |
| 4 | *counter-example* — `--where component=payments-api`, which no document carries | the first line, `incidents · 0 documents · not filtered by reader`, then `no documents found`; exit 0 |
| 5 | a chunk's text of `incident` thirty times, over three lines, 269 characters | on one line, cut at the last space within 200 characters: `incident` 22 times, 197 characters, then `…` |
| 6 | *counter-example* — `INC-4830`'s root cause over two lines; a text of exactly 200 characters | each shown whole, on one line, with no `…`: a text that fits is not cut |
| 7 | a text that is one word of 250 characters | its first 200 characters, then `…`: a word longer than the line is cut where the line ends |

### R19.10 — `--as READER`, repeatable, keeps only the chunks one of the readers named may read

A person often reads as more than one reader, and an agent searching for them
asks as all of theirs at once: `--as incident-response --as sre` lists what
either may read, in one ranked list. Each reader must be declared by a source
of the pipeline. When it lands, it supersedes R19.5, whose search without
`--as` is R19.11's.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.readers_for`), infrastructure (`dossier.infrastructure.index.postgres`)
- **Proved by:** `tests/unit/test_R019_10__as_keeps_what_a_named_reader_may_read.py`, `tests/integration/test_R019_4__postgres_search_filters.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-jira` declaring `[incident-response]`, `procedures-confluence` declaring `[sre]`; `--as incident-response` | `incidents-jira`'s documents only; the first line says `as incident-response` |
| 2 | the same, `--as incident-response --as sre` | both sources' documents, in one ranked list; the first line says `as incident-response, sre` |
| 3 | the same, `--as sre --as incident-response --as sre` | as row 2: each reader once, in order |
| 4 | *counter-example* — `--as incident-responce --as sre` | exit 2, `no source of incident-audit declares incident-responce as a reader; they declare incident-response, sre`; 0 embedding calls. A typo would otherwise narrow the search silently |

### R19.11 — a search names its readers, or asks for every chunk with `--all-readers`; with neither, it is refused before the model is asked

The connection string reads every row, so the application holding it is what
keeps readers apart ("Decisions"). A search that names no reader would list
every chunk, whoever it was for, and an agent that forgot `--as` would show
someone everything. Asking for everything is a choice, and says so.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.search.readers_for`), cli (`dossier.cli.search`)
- **Proved by:** `tests/unit/test_R019_11__a_search_names_its_readers.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier search incidents "certificate expired at checkout"`, with neither | exit 2, `name the readers this search is for with --as READER (incident-response, sre), or search every chunk with --all-readers`; 0 embedding calls |
| 2 | the same, `--all-readers` | both sources' documents; the first line says `not filtered by reader` |
| 3 | *counter-example* — `--as sre --all-readers` | exit 2, `--as and --all-readers contradict: name the readers, or ask for every chunk`; 0 embedding calls |

### R19.12 — `dossier search INDEX QUERY --as READER` prints the documents that answer it, best first

The slice's acceptance rule, through the CLI, with the embedding model and the
index as fakes, as R18.7's are. When R19.10 and R19.11 land, it supersedes
R19.8, whose searches name no reader.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.search`), domain (`dossier.domain.search.excerpt`)
- **Proved by:** `tests/acceptance/test_R019_12__search_lists_what_answers_the_query_for_its_readers.py`, `tests/unit/test_R019_12__a_result_shows_its_text_on_one_line.py`
- **Status:** IN PROGRESS

| # | Given | Then |
|---|-------|------|
| 1 | R18.11's workspace, synced, run and embedded; `dossier search incidents "certificate expired at checkout" --as incident-response` | the first line, `incidents · 1 document · as incident-response`; then `1. INC-4830`, its title, the heading path of its best chunk, its text on one line cut at a word to at most 200 characters, and its carried values; exit 0 |
| 2 | the same, `--json` | one JSON object: `index`, `query`, `readers` (`["incident-response"]`, and `null` with `--all-readers`), and `results`, each with `rank`, `document_id`, `title`, `values`, the chunk's `heading_path`, `kind` and `text`, and its `score`; nothing else on stdout |
| 3 | *counter-example* — `dossier search incidents "kubernetes" --as incident-response`, which no chunk matches by words, and only far chunks by meaning | the documents by meaning still listed: a fusion of one list is that list |
| 4 | *counter-example* — `--where component=payments-api`, which no document carries | the first line, `incidents · 0 documents · as incident-response`, then `no documents found`; exit 0 |
| 5 | a chunk's text of `incident` thirty times, over three lines, 269 characters | on one line, cut at the last space within 200 characters: `incident` 22 times, 197 characters, then `…` |
| 6 | *counter-example* — `INC-4830`'s root cause over two lines; a text of exactly 200 characters | each shown whole, on one line, with no `…`: a text that fits is not cut |
| 7 | a text that is one word of 250 characters | its first 200 characters, then `…`: a word longer than the line is cut where the line ends |

### R19.9 — a chunk's words are its heading path and its text, the text its vector was made from

`text_search` is the `tsvector` of what R18.3 embeds: the chunk's heading
path, then its text. A note's key and title are in its first heading, which
every chunk beneath it carries in its heading path and none holds in its text.
Searched by its text alone, a chunk is near its key in meaning and does not
hold it in words, and a search for `PLAY-1004` listed `PLAY-1004` third (the
live check of R19.8). An index written before this rule has its words rebuilt
from the heading paths and texts it holds the next time `dossier embed`
prepares it; nothing is embedded again.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.index.postgres.PostgresIndexSink`), domain (`dossier.domain.index.embedding_text`)
- **Proved by:** `tests/integration/test_R019_9__a_chunks_words_are_its_heading_path_and_text.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821`'s chunk holding `CHF 48'200`, heading path `["INC-4821 — Card payments declined at checkout", "Impact"]`, `INC-4821` nowhere in its text; the query `INC-4821` | the chunk is in the list by words |
| 2 | that chunk and the one under `Comments`; the query `declined at checkout`, words of the title alone | both in the list by words: each carries the title in its heading path |
| 3 | an index written before R19.9, its words its chunks' texts alone; prepared again, as each `dossier embed` prepares it | row 1's chunk found by `INC-4821`, its id and vector unchanged: the words are rebuilt from what the index holds |
| 4 | *counter-example* — `audit-note.pdf`'s chunk, heading path `[]` | its words are its text's alone, as its embedded text is its text alone |
