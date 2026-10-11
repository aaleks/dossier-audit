# 20 · An index to search by meaning

**You will build:** an index of exercise 05's four incident notes in
PostgreSQL. Each note is cut at its headings, and each piece is held twice, as a
vector to search by meaning and as words to search by words. Each note carries
the categories its run found, for as long as the note is the one the run read.

**You will learn:** what `dossier embed` writes, and why a second one asks and
writes nothing:

- what a chunk is, and what it carries besides its text: its headings and its
  readers;
- how a search by words and a search by meaning each go wrong, and how
  differently;
- why a run's categories are carried only while the note is the one the run
  read;
- which declarations are refused before a model is asked anything;
- what an `embed` records in MLflow, and what it does not.

**Needs Docker, Ollama and about 10 GB of free RAM. No API key, no model bill,
no stub. Task 7 needs an MLflow server, as exercise 08 does.**

---

## Read this before you start

The embedding model is `qwen3-embedding:4b-fp16`: 8 GB of weights, 2,560
numbers a vector, and on a machine without a GPU it runs on the CPU. The first
build of this index takes about a minute, and the model holds about 10 GB of
RAM while it is loaded. Close what you can before task 1. After the first
build, only a chunk whose text changed is ever embedded again, which is the
point of task 5.

A vector is a model's answer, worked out on your CPU, so the distances in task
3 may differ from `SOLUTION.md`'s in the last digit or two. The chunk ids and
the counts should be the same.

---

## Background, in one paragraph

Until now, what `dossier` held could be searched only by the categories a run
extracted. A question such as "why did adding servers make it slower?" has no
category to filter on, and the words of a note were not indexed at all.
`dossier embed INDEX` writes a pipeline's documents into PostgreSQL twice over,
as vectors and as text, and carries the run's categories along as values to
filter on (spec 018). An index is declared in a file of its own,
`indexes/<name>.yaml`, so declaring one changes neither the pipeline's hash nor
its version. The index is derived data. Everything in it is rebuilt from the
workspace: the snapshots, their conversions, the runs, and a cache of vectors
under `.dossier/cache/embed/`. Here you search it by hand, with SQL and a few
lines of Python, to see what a search is made of. Exercise 21 asks it the same
questions with `dossier search` (spec 019).

---

## Setup

From the repository root:

```bash
docker compose -f dev/index/docker-compose.yml up -d     # Postgres 17 + pgvector, 127.0.0.1:5435
docker compose -f dev/index/docker-compose.yml ps        # wait for (healthy)
ollama pull qwen3-embedding:4b-fp16                      # 8 GB, once
uv sync --all-extras --no-extra docling                  # the index extra: psycopg and pgvector

mkdir -p playground/work/20
cp -r playground/work/05/. playground/work/20/
cd playground/work/20
echo "DOSSIER_INDEX_DSN=postgresql://dossier:dossier@127.0.0.1:5435/dossier" >> .env

D=../../../.venv/bin/dossier
P=../../../.venv/bin/python
Q() { docker exec dossier-index psql -U dossier -d dossier -c "$1"; }
```

`dev/README.md`, "The embedding index", says what the container is. Ollama is
reached at `http://localhost:11434` unless `DOSSIER_OLLAMA_URL` says otherwise.

Nothing in this exercise runs the pipeline. The index carries the latest run
exercise 05 left you. `SOLUTION.md`'s pass started from a run made with task
2's prompt. If yours is task 3's, one value in task 4 differs, and task 4 asks
about it.

## Task 1 — declare and build

A source the index reads must say who may read it. Add one line to
`incidents-manual` in `sources.yaml`:

```yaml
    acl: [incident-response]
```

Then write `indexes/incidents.yaml`:

```yaml
pipeline: incident-audit
embedding_model: ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
chunker: {name: headings, max_chars: 2000}
target: {dsn_env: DOSSIER_INDEX_DSN}
```

```bash
time $D embed incidents
time $D embed incidents
```

**Checkpoint.** The first `embed` takes about a minute and ends
`incidents · 21 chunks · 21 embedded · 0 cached · 4 written · 0 removed`. The
second takes about a second: `0 embedded · 21 cached · 0 written · 0 removed`.

- **What `written` counts.** 21 chunks were embedded, and 4 were written. 4 of
  what? Why is the second `embed`'s `0 written` the right answer, even though it
  read every note again (R18.4)?
- **Where the vectors were.** The second `embed` asked the model nothing. Look
  under `.dossier/cache/embed/`. What is a vector filed under? A second index
  over the same notes, pinning the same model, would ask how many times
  (R18.3 rows 1 and 4)?
- **Why a file of its own.** The index names its pipeline, and the pipeline
  does not name the index. What would declaring the index in `pipeline.yaml`
  have done to the pipeline's hash and its version, and why should it not
  (spec 013)?

## Task 2 — look at what was written

```bash
Q "select key, title, acl, run_id, filter_values from dossier_index.documents
   where index = 'incidents' order by key"
Q "select d.key, c.chunk_index, c.kind, c.heading_path, length(c.text) as chars, c.acl
   from dossier_index.chunks c join dossier_index.documents d using (index, document_id)
   where c.index = 'incidents' order by d.key, c.chunk_index"
Q "select text from dossier_index.chunks
   where index = 'incidents' and document_id = 'incidents-manual:PLAY-1001.md'
   and chunk_index in (0, 3) order by chunk_index"
Q "select format_type(atttypid, atttypmod) as embedding_type from pg_attribute
   where attrelid = 'dossier_index.chunks'::regclass and attname = 'embedding'"
Q "select indexdef from pg_indexes where indexname = 'chunks_embedding'"
Q "select text_search from dossier_index.chunks
   where index = 'incidents' and document_id = 'incidents-manual:PLAY-1001.md'
   and chunk_index = 3"
```

**Checkpoint.** Four document rows, each titled by its note's first heading,
each with `acl` `{incident-response}`, no `run_id` and `{}`. 21 chunk rows: five
for each note and six for `PLAY-1004`, which has a `Notes` section. Every chunk
is of kind `body`. The column is `halfvec(2560)`, under an `hnsw` index with
`halfvec_cosine_ops`.

- **The headings.** Chunk 0 of each note holds three lines (severity, date,
  systems), and none holds a heading. Where did the headings go? What text was
  actually embedded for the chunk holding `CHF 18'400`, and why does it matter
  that a search for "the checkout incident's impact" can find it
  (R18.1 row 1, R18.3)?
- **The column.** Why `halfvec` and not `vector`? What would a model answering
  1,024 numbers be written as, and one answering 4,001 (R18.5)?
- **The readers.** `acl` is on every chunk row, not only on the document row.
  Who reads it? `embed` never reads it back, so who must put
  `'incident-response' = any(acl)` into a query (R18.6, "Decisions")?
- **The words.** `text_search` holds `'play':1 '-1001':2`, `'18':27 '400':28`
  and `'s':19`. Where do its first ten words come from, when the chunk's text
  starts with `Finance` (R19.9)? What did the `simple` configuration do to
  `PLAY-1001`, `CHF 18'400` and `gateway's`, and what did it not do that
  `english` would have ("What it writes")?

## Task 3 — search it two ways

By words. `plainto_tsquery` keeps every word, and a chunk must hold them all:

```bash
Q "select d.key, c.heading_path[cardinality(c.heading_path)] as section
   from dossier_index.chunks c join dossier_index.documents d using (index, document_id)
   where c.index = 'incidents' and c.text_search @@ plainto_tsquery('simple', 'warehouse')
   order by d.key, c.chunk_index"
```

Run it for `warehouse`, `timeout`, `timeouts`, `autoscaler` and
`warehouse outage cost`.

By meaning. Save this as `search.py`. It asks Ollama for the question's vector
through `dossier`'s own client, and asks Postgres for the three nearest chunks:

```python
import sys

import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector

from dossier.infrastructure.models.ollama_embed import ollama_embeddings

MODEL = "ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
DSN = "postgresql://dossier:dossier@127.0.0.1:5435/dossier"

# Qwen3-Embedding wants a query to say what it is for. A document is embedded as it is.
query = "Instruct: Given an incident question, retrieve passages that answer it\nQuery: " + sys.argv[1]
[vector] = ollama_embeddings(MODEL, url="http://127.0.0.1:11434").embed([query])

with psycopg.connect(DSN) as db:
    register_vector(db)
    rows = db.execute(
        """
        select d.key, c.heading_path[cardinality(c.heading_path)],
               round((c.embedding <=> %(q)s)::numeric, 3), left(c.text, 60)
        from dossier_index.chunks c join dossier_index.documents d using (index, document_id)
        where c.index = 'incidents' and 'incident-response' = any(c.acl)
        order by c.embedding <=> %(q)s
        limit 3
        """,
        {"q": HalfVector(vector)},
    ).fetchall()
for key, heading, distance, text in rows:
    print(f"{distance}  {key}  {heading}  {text!r}")
```

```bash
$P search.py "How much did the warehouse outage cost?"
$P search.py "Why did adding servers make it slower?"
$P search.py "Which incident was caused by a misconfigured autoscaler?"
```

`<=>` is pgvector's cosine distance: 0 is the same direction, and smaller is
nearer.

**Checkpoint.** By words, `warehouse` finds three chunks of `PLAY-1002` and all
five of `PLAY-1003`'s, `timeouts` all five of `PLAY-1001`'s and `timeout` two,
and `warehouse outage cost` finds nothing. By meaning, the cost
question's first answer is `PLAY-1003`'s `Impact`, all three answers to the
slowness question are `PLAY-1004`'s, and the autoscaler question's first answer
is `PLAY-1004`'s `Notes`.

- **Found by its title.** `warehouse` finds every chunk of `PLAY-1003`, which
  is titled "Warehouse terminals offline". Which word of which chunk matched,
  and would any of them match by its text alone? Why does it find the export
  incident too? Why does `timeouts` find all five of `PLAY-1001`'s chunks, and
  `timeout` only two? Which causes are properties of `simple`, and which of
  what `text_search` is made of (R18.3, R19.9)?
- **The other way round.** Read `PLAY-1004`'s `Notes`. Does it answer the
  autoscaler question? What does a distance measure, and what can it not tell
  apart? What would a reader of this index need on top of `<=>` before showing
  the first answer as the answer?
- **The instruction.** The question was embedded behind an instruction, and the
  chunks were embedded without one. Why is the instruction the search's
  business and not `dossier`'s ("Left out on purpose")?
- **The `where`.** Take `'incident-response' = any(c.acl)` out. What changes
  here, and what would change in an index that also read a source declaring
  `acl: [finance]`?

## Task 4 — carry the run's record

Read `pipelines/incident-audit/schemas/incident.yaml`. Its four fields are an
`amount`, a `date`, an `enum` and a `reference`, and none is `free_text`. Carry
two of them as values to filter on. Add to `indexes/incidents.yaml`:

```yaml
fields:
  filter: [severity, affected_systems]
```

```bash
$D embed incidents
Q "select key, run_id, filter_values from dossier_index.documents
   where index = 'incidents' order by key"
Q "select key from dossier_index.documents
   where index = 'incidents' and filter_values ->> 'severity' = 'major' order by key"
```

**Checkpoint.** `incidents · 21 chunks · 0 embedded · 21 cached · 4 written · 0
removed`. Every document row names your latest run, and holds its two values:
`PLAY-1003.md` is `{"severity": "critical", "affected_systems":
"terminal-gateway, inventory-sync"}`. `major` finds `PLAY-1001` and `PLAY-1004`.

- **Written, not embedded.** Four documents were written and nothing was
  embedded. What changed in each row, and why did no vector have to (R18.4,
  "What it writes")?
- **Only what was grounded.** Open each note's answer under `runs/<id>/extract/`
  and find each value's span in its note. What would `embed` have printed for a
  value whose span is not there, and why is such a value never carried, even
  when it is right (R18.9 row 3)?
- **No record chunk.** Every chunk is still `body`. What kind of field would
  have added a chunk of kind `record`, and why does this schema have none
  (R18.9 row 2, exercise 07)?
- **A system to filter on.** Find every incident that touched
  `payments-gateway` with an exact filter. Why can't you? What kind would have
  let you (exercise 19)?
- **`MAJOR`.** Exercise 05's task 3 run answered `PLAY-1001`'s severity
  `MAJOR`. Why did eval score it correct, and in which spelling is it carried?
  What would `= 'major'` miss if it were carried as answered (R18.9 row 5,
  R6.26)?

## Task 5 — change a note after the run

Add a line to the end of `PLAY-1003`'s follow-up list, then sync and embed:

```bash
echo "- Keep decommissioned ranges in the inventory, marked as retired, so a change can be checked against them." \
  >> inbox/incidents/PLAY-1003.md
$D sync incident-audit
time $D embed incidents
Q "select key, left(snapshot, 12) as snapshot, run_id, filter_values
   from dossier_index.documents where index = 'incidents' order by key"
```

**Checkpoint.** The sync finds one note changed. The embed prints one line
before its count:

```
PLAY-1003.md: record stale: <your run id> read an earlier snapshot
incidents · 21 chunks · 1 embedded · 20 cached · 1 written · 0 removed
```

`PLAY-1003.md`'s row holds the new snapshot, no `run_id` and `{}`. The other
three keep theirs.

- **Still true, and dropped.** The sentence you added changes neither the
  severity nor the systems. Why is the run's answer dropped anyway? What would
  `dossier` have to know to keep it, and where would that knowledge come from
  (R18.8 row 2)?
- **One vector.** Which chunk was embedded? Why not all five of `PLAY-1003`'s
  (R18.3 row 2)?
- **Getting it back.** What brings `PLAY-1003`'s categories back, and which run
  would its row then name (R18.11 row 3)?

## Task 6 — refusals

Make each change below, run `$D embed incidents; echo "exit $?"`, read the
message, and **put the change back before the next one**:

1. Remove the `acl:` line from `sources.yaml`. Then write it as `acl: []`.
2. In `indexes/incidents.yaml`, write `filter: [severity, root_cause]`.
3. Write `filter: [severity]` and `embed: [affected_systems]`.
4. Pin the model by its tag alone: `ollama:qwen3-embedding:4b-fp16`.
5. Take `DOSSIER_INDEX_DSN` out of `.env` (or `unset` it, if you exported it).
6. And one that is not a refusal: put it back with `wrong` as the password.

**Checkpoint.** The first five exit `2`, each naming what to fix. The last
exits `1`: `reading what index 'incidents' holds failed: connection failed: …
password authentication failed for user "dossier"`.

- **Before anything.** None of the five asked the model anything or touched
  Postgres. Why must a missing connection string be found before the first
  vector is asked for, and not when the first row is written (R18.7 row 3)?
- **`acl: []`.** It is refused in `sources.yaml` itself, so it stops `sync` too,
  while a missing `acl` stops only `embed`. Why is an empty list not taken to
  mean "nobody may read this" (R18.6 rows 2 and 3)?
- **The wrong list.** `root_cause` is refused as undeclared, naming the fields
  that are declared. This schema has no `free_text` field, so you cannot see
  R18.10 row 2's refusal here. What would it say, and why is free text embedded
  and never filtered?
- **A tag.** A tag moves when the model is re-pulled. What would happen to
  every vector in the cache, and to every search, if the index held a tag
  (R18.10 row 4, R18.3 row 3)?
- **2 and 1.** Why is a wrong password not exit `2`? Which of the two is a
  mistake in the workspace, and which is a server that answered?

## Task 7 — with tracking on

Start the MLflow server from exercise 08, and add to `.env`:

```
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5000
```

Change another note, and sync and embed:

```bash
echo "- Alert when the pool hands out a socket the balancer has already closed." \
  >> inbox/incidents/PLAY-1001.md
$D sync incident-audit
$D embed incidents
```

Then read the newest `embed` run back. Save this as `read_embed_run.py`:

```python
import mlflow

mlflow.set_tracking_uri("http://127.0.0.1:5000")
[run] = mlflow.search_runs(
    experiment_names=["dossier-audit/incident-audit/embed"],
    order_by=["attributes.start_time DESC"],
    max_results=1,
    output_format="list",
)
print(run.info.run_name, run.info.status)
print("tags   ", {k: v for k, v in run.data.tags.items() if k.startswith("dossier.")})
print("params ", run.data.params)
print("metrics", run.data.metrics)
traces = mlflow.search_traces(
    locations=[run.info.experiment_id], run_id=run.info.run_id, return_type="list"
)
for trace in traces:
    print("trace  ", trace.info.tags.get("mlflow.traceName"), trace.info.state)
    for span in trace.data.spans:
        if span.span_type == "EMBEDDING":
            print("  span ", span.span_type, span.attributes["dossier.model"])
            print("       chunks", span.attributes["dossier.chunks"])
            print("       tokens", span.attributes["dossier.tokens"])
```

```bash
$P read_embed_run.py
$D embed incidents
```

Last, empty the index by hand, and embed once more:

```bash
Q "delete from dossier_index.documents where index = 'incidents'"
$D embed incidents
$P read_embed_run.py
```

**Checkpoint.** The first `embed` ends `recorded to MLflow:
dossier-audit/incident-audit/embed`, and the second records nothing. The run is
named `embed incidents <when it started>`, its params are the index and the
pinned model, and its metrics are the five counts the line printed. It has one
trace, with one `EMBEDDING` span naming one chunk id and the tokens the model
counted. After the delete: `0 embedded · 21 cached · 4 written`, recorded, and
no trace at all.

- **What is recorded.** The second `embed` recorded nothing, and the one after
  the delete did, with no trace. What decides whether an `embed` is a run, and
  what decides how many traces it has (R11.33 rows 2 and 4)?
- **A chunk id.** The span names a chunk by its id, not its text. Find the id
  in `dossier_index.chunks`. Which chunk is it, and what is the id the hash of
  (R18.2)? Why would a chunk cut with `max_chars: 1000` have another id, even
  where its text came out the same?
- **Derived data.** The `delete` cascaded to all 21 chunks, and nothing was
  embedded to put them back. What is Postgres in this design, and what would you
  have to lose to make the next `embed` ask the model again (R18.4 row 5)?
- **The first build.** It ran with tracking off. Had it been on, how many traces
  would 21 chunks have made? Look for `BATCH` in
  `src/dossier/application/embed.py`.

---

## Done when

- you can say what `dossier embed` asks the model for and what it writes, and
  why a second `embed` with nothing changed does neither;
- you can find a chunk's headings, its readers and its vector's type in
  Postgres, and say what was embedded for it;
- you have searched by words and by meaning, seen each miss something the other
  found, and can say why a nearest chunk is not always an answer;
- you can say why a run's categories are carried, why only grounded ones, and
  why a note changed after the run loses them;
- you have seen each declaration refused before any work, with its message, and
  know which mistake is exit 2 and which is exit 1;
- you have read an `embed`'s MLflow run back, and can say when an `embed` is
  recorded and when it is not.

## Cleaning up

```bash
Q "delete from dossier_index.chunks where index = 'incidents'"
Q "delete from dossier_index.documents where index = 'incidents'"
rm -rf playground/work/20                                # from the repository root
docker compose -f dev/index/docker-compose.yml down      # keeps the data; down -v drops it
```

Ollama unloads the model after five minutes idle. `ollama rm
qwen3-embedding:4b-fp16` frees its 8 GB on disk.

**Back to:** [the playground index](../README.md).
