# 21 · Asking the index a question

**You will build:** nothing new. You ask exercise 20's index questions with
`dossier search`, and read what it answers: which notes, at which section, in
which order, and why.

**You will learn:** how a search turns two rankings into one, and where it
stops being able to help:

- why a search names the readers it is for, and what it does when it names
  none;
- why every note is listed for a question only one of them answers;
- how a ranking by meaning and a ranking by words are fused, and what decides
  a tie;
- why an incident key is found by its words, and a question in plain English
  is found by meaning alone;
- what a filter on a run's values matches, and what it refuses before the model
  is asked anything;
- what a search says about the notes the index has not seen;
- what a search writes, and what it records in MLflow;
- how well a search ranks, measured against questions you judged yourself,
  and what four notes can and cannot tell you about it.

**Needs what exercise 20 needs: Docker, Ollama and about 10 GB of free RAM. No
API key, no model bill, no stub. Task 7 needs an MLflow server, as exercise 08
does.**

---

## Read this before you start

Each new question is one call to `qwen3-embedding:4b-fp16`, on the CPU: about
a second with the model in memory, and longer while Ollama loads it again after
five idle minutes. A question asked before is not asked again (task 6).

A vector is a model's answer, worked out on your CPU, so a rank in
`SOLUTION.md` may differ from yours where two chunks are nearly as near as each
other. The chunk ids, the filters, the refusals and the counts should be the
same.

---

## Background, in one paragraph

Exercise 20 built an index and searched it by hand: by words, with SQL, and by
meaning, with a few lines of Python. Each search missed what the other found.
`dossier search INDEX QUERY` asks both at once (spec 019). It asks the index
for the 100 chunks nearest the question's vector and the 100 that hold every
word of it, and fuses the two ranked lists by **reciprocal rank**: a chunk's
score is `1 / (60 + rank)` in each list it is in, added up. Each note is listed
once, at its best chunk, with the values its run carried. The ranking is a
pure decision over two lists, so it is the same on every machine. The search
changes nothing in the workspace or the index. It writes the question's vector
to the cache, and nothing else. And it names the readers it is for, with
`--as`: the index's connection string reads every row, so the search is what
keeps readers apart, and one naming no reader is refused unless it asks for
every chunk with `--all-readers` (R19.10, R19.11).

---

## Setup

From the repository root, with exercise 20's container and model:

```bash
docker compose -f dev/index/docker-compose.yml up -d     # Postgres 17 + pgvector, 127.0.0.1:5435
ollama pull qwen3-embedding:4b-fp16                      # 8 GB, once
uv sync --all-extras --no-extra docling

mkdir -p playground/work/21
cp -r playground/work/05/. playground/work/21/
cd playground/work/21
echo "DOSSIER_INDEX_DSN=postgresql://dossier:dossier@127.0.0.1:5435/dossier" >> .env

D=../../../.venv/bin/dossier
P=../../../.venv/bin/python
Q() { docker exec dossier-index psql -U dossier -d dossier -c "$1"; }
```

Then set it up as exercise 20's tasks 1 and 4 leave it. Add `acl:
[incident-response]` to `incidents-manual` in `sources.yaml`, and write
`indexes/incidents.yaml`:

```yaml
pipeline: incident-audit
embedding_model: ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
chunker: {name: headings, max_chars: 2000}
fields:
  filter: [severity, affected_systems]
target: {dsn_env: DOSSIER_INDEX_DSN}
```

```bash
$D embed incidents
```

**Checkpoint.** `incidents · 21 chunks · 21 embedded · 0 cached · 4 written · 0
removed`, in about a minute. If you kept exercise 20's workspace, copy its
`.dossier/cache/embed/` across first, and fewer chunks are embedded: a vector
is filed under the model and the text, and not under the workspace (R18.3).

Save this as `ranks.py`. It prints one line per result of a `--json` search:

```python
import json
import sys

found = json.load(sys.stdin)
for result in found["results"]:
    section = result["heading_path"][-1] if result["heading_path"] else ""
    print(
        result["rank"],
        result["document_id"].partition(":")[2],
        f"{section[:24]:24}",
        f"{result['score']:.6f}",
        "meaning",
        result["meaning_rank"],
        "words",
        result["words_rank"],
    )
```

## Task 1 — ask it a question

Exercise 20 asked this question with `search.py`. Ask it first as it is, then
as the one reader `sources.yaml` declares:

```bash
$D search incidents "How much did the warehouse outage cost?"; echo "exit $?"
$D search incidents "How much did the warehouse outage cost?" --as incident-response
$D search incidents "How much did the warehouse outage cost?" --as incident-response --limit 2
```

**Checkpoint.** The first search exits `2`: `name the readers this search is
for with --as READER (incident-response), or search every chunk with
--all-readers`. The second's first line is `incidents · 4 documents · as
incident-response`. `PLAY-1003` comes first, at its `Impact` section, which says `CHF
61'250`, with the two values its run carried. All four notes are listed, each
at its `Impact`. With `--limit 2`, `PLAY-1003` and `PLAY-1002`.

- **Four of four.** The question is about one incident, and every note is
  listed. Why does a search always have a nearest chunk, however far it is?
  What would tell you where the answers stop ("Left out on purpose")?
- **Once each.** `PLAY-1003` has five chunks. Why is it listed once, and which
  of its chunks stands for it (R19.2)?
- **The second answer.** Read `PLAY-1002`'s line. Does it answer the question?
  Compare exercise 20's task 3, "The other way round".
- **No reader.** The first search was refused, and asked the model nothing.
  The index's connection string reads every row. So who keeps readers apart,
  and why is a search that names none refused, rather than answered with every
  chunk (R19.11, "Decisions")?

## Task 2 — two lists, one order

```bash
$D search incidents "How much did the warehouse outage cost?" --as incident-response --json --limit 2
$D search incidents "How much did the warehouse outage cost?" --as incident-response --json --limit 2 | $P ranks.py
$D search incidents "warehouse" --as incident-response --json --limit 3 | $P ranks.py
$D search incidents "warehouse or cost" --as incident-response --json --limit 3 | $P ranks.py
$D search incidents "PLAY-1004" --as incident-response --limit 2
```

Then see how the words list ranks `warehouse`:

```bash
Q "select d.key, c.heading_path[cardinality(c.heading_path)] as section,
          ts_rank_cd(c.text_search, q) as words, left(c.chunk_id, 8) as chunk
   from dossier_index.chunks c join dossier_index.documents d using (index, document_id),
        websearch_to_tsquery('simple', 'warehouse') q
   where c.index = 'incidents' and c.text_search @@ q
   order by words desc, c.chunk_id collate \"C\""
```

**Checkpoint.** The question's two results have `words_rank` `null`, and
scores `0.016393` and `0.015873`. `warehouse` lists `PLAY-1002`'s `Follow-up`
first, at `0.032266`, ahead of `PLAY-1003`'s `Impact`, at `0.032018`. Under
`warehouse or cost`, the same two score exactly `0.032018` each, `PLAY-1002`
first. `PLAY-1004` lists `PLAY-1004` first. By words, all eight chunks holding
`warehouse` rank `0.1`.

- **The arithmetic.** Work out each score from its ranks with `1 / (60 +
  rank)`. Why does the fusion add up ranks, and not the cosine distance and the
  `ts_rank_cd` themselves (R19.1, "How a search ranks")?
- **Nothing by words.** Which words of the question did the words list require,
  and which one is in no chunk? What did `or` change? Why is a question in plain
  English so often ranked by meaning alone (R19.12 row 3, open question 2)?
- **The export incident first.** `PLAY-1002` is about a warehouse *load*, and
  `PLAY-1003` is the warehouse incident. All eight chunks rank `0.1` by words.
  What put `PLAY-1002`'s follow-up first in that list, and is that a reason
  anyone would give? What would a ranking that counted a word's rarity, or a
  chunk's length, have done ("Existing options considered")?
- **A tie.** Under `warehouse or cost`, two chunks score the same to the last
  digit. What decides which is first, and why must something decide it
  (R19.1 row 3)?
- **A key.** `PLAY-1004` is near nothing in meaning. Which list found it, and in
  which part of which chunk is the word it matched? Exercise 20's
  `text_search` would not have held it. Why not, and what changed (R19.9)?

## Task 3 — chunks or documents

```bash
$D search incidents "firewall rule" --as incident-response --chunks --limit 4
$D search incidents "firewall rule" --as incident-response --limit 4
```

**Checkpoint.** With `--chunks`, four chunks, all of `PLAY-1003`: its root
cause, follow-up, timeline and first chunk. Without it, four notes: `PLAY-1003`
at its root cause, then `PLAY-1001`, `PLAY-1002` and `PLAY-1004`.

- **One note fills the list.** Why are documents the default (R19.2 row 4,
  "Decisions")? When would you want `--chunks`?
- **The same first line.** Is a note's line always at the chunk `--chunks` lists
  first for it? Why (R19.2)?
- **Three more notes.** No other note mentions a firewall. Why are three more
  listed, and what on their lines would tell a reader that they are not
  answers?

## Task 4 — filters and readers

```bash
V() { find .dossier/cache/embed -name '*.meta.json' | wc -l; }   # the vectors cached

$D search incidents "slow responses for customers" --as incident-response --where severity=MAJOR
$D search incidents "slow responses for customers" --as incident-response --where severity=major --where severity=critical --limit 3
$D search incidents "slow responses for customers" --as incident-response --where severity=major \
  --where "affected_systems=search-api, catalogue-index"
$D search incidents "slow responses for customers" --as incident-response --where affected_systems=search-api
$D search incidents "slow responses for customers" --all-readers --limit 1
V
$D search incidents "who was paged" --as sre; echo "exit $?"
$D search incidents "who was paged" --as incident-response --as sre; echo "exit $?"
$D search incidents "who was paged" --as incident-response --all-readers; echo "exit $?"
$D search incidents "who was paged" --as incident-response --where loss_amount=18400; echo "exit $?"
$D search incidents "who was paged" --as incident-response --where severity=huge; echo "exit $?"
V
```

**Checkpoint.** `MAJOR` lists `PLAY-1004` and `PLAY-1001`. `major` or
`critical` adds `PLAY-1003`. `major` with `PLAY-1004`'s two systems lists
`PLAY-1004` alone. `search-api` alone: `no documents found`.
`--all-readers` changes the first line to `not filtered by reader`. The five
refusals exit `2`, each naming what is declared, and `V` prints the same number
before and after them.

- **`MAJOR`.** The values are carried as the declaration spells them (exercise
  20, task 4). What did `dossier` do to `MAJOR` before asking the index, and
  why there rather than in a case-blind comparison in SQL (R19.4)?
- **Or, and.** One field given twice is a choice, and two fields must both be
  carried. Why that way round?
- **A system.** `PLAY-1004` touched `search-api`, and `--where
  affected_systems=search-api` does not find it. Why? What would the field have
  to be declared as to be filtered on one system (exercise 19, "How a search
  ranks")?
- **Before the model.** `who was paged` was never asked of the model: `V` did
  not move. Why refuse a filter or a reader before the question is embedded
  (R19.4 rows 5 and 6, R19.10, R19.11)?
- **A reader nobody declared.** Why is `sre` refused rather than answered with
  no documents? And beside `incident-response`, why is it refused rather than
  ignored? What would either answer have told an agent that mistyped a reader
  (R19.10 row 4)?
- **Two readers.** Were `sre` declared on another source, `--as
  incident-response --as sre` would list what either may read, in one ranked
  list. Why is that better than two searches merged afterwards (R19.10,
  task 2)?
- **Every chunk.** When is `--all-readers` the right flag, and why must it be
  asked for, and not be what a search with no `--as` does (R19.11)?

## Task 5 — what the index has not seen

Add a fifth note, and search before and after embedding it:

```bash
cat > inbox/incidents/PLAY-1005.md <<'EOF'
# PLAY-1005 — Refunds issued twice after a payment retry

**Severity:** major
**Resolved:** 2026-06-02
**Systems affected:** payments-gateway

## Impact

Refunds were issued twice for 31 orders before the retry was stopped.
EOF
$D sync incident-audit
$D search incidents "refunds issued twice" --as incident-response --limit 2
$D embed incidents
$D search incidents "refunds issued twice" --as incident-response --limit 2
```

Then take it away again:

```bash
rm inbox/incidents/PLAY-1005.md
$D sync incident-audit
$D search incidents "refunds issued twice" --as incident-response --limit 1
$D embed incidents
```

Last, change the last character of the model's digest in
`indexes/incidents.yaml` from `c` to `d`, search, and put it back:

```bash
$D search incidents "refunds issued twice" --as incident-response; echo "exit $?"
```

**Checkpoint.** After the sync, the search does not list `PLAY-1005`, and its
last line is `1 held document not in incidents as held: run dossier embed
incidents`. The embed prints `PLAY-1005.md: no record: <your run id> did not
read it`, then `23 chunks · 2 embedded · 21 cached · 1 written · 0 removed`,
and `PLAY-1005` comes first, with no values line. After the `rm` and the sync,
the search still lists `PLAY-1005`, and says `1 held document` again. The embed
removes it: `21 chunks · 0 embedded · 21 cached · 0 written · 1 removed`. The
changed digest exits `2`, naming both pins.

- **Saying so.** The search knew the index was behind. Why does it count what
  the index has not seen, rather than embed it there and then (R19.3, R19.7)?
- **A deleted note, found.** Why is `PLAY-1005` still listed after its file was
  deleted, and what on the screen says it should not be?
- **No values.** `PLAY-1005` says `**Severity:** major`, and carries no
  severity. Why not, and what would carry one (R18.8)?
- **Another model.** Why refuse rather than search? What would a question's
  vector from one model be compared with, in an index embedded by another
  (R19.6)?

## Task 6 — the question's vector

```bash
V
$D search incidents "Why did adding servers make it slower?" --as incident-response --json --limit 3 | $P ranks.py
V
$D search incidents "Why did adding servers make it slower?" --as incident-response --limit 1
V
echo 'query_instruction: ""' >> indexes/incidents.yaml
$D search incidents "Why did adding servers make it slower?" --as incident-response --json --limit 3 | $P ranks.py
V
```

Take the `query_instruction` line out again when you are done.

**Checkpoint.** `V` grows by one, stays, then grows by one again. Both times
`PLAY-1004`'s `Root cause` is first, then `PLAY-1001`'s root cause, then
`PLAY-1003`'s first chunk, and `PLAY-1001`'s rank by meaning moves by one.

- **One more, then none.** What is the question's vector filed under? Why is
  it the only thing a search writes, and why is it safe to write (R19.3)?
- **The instruction.** By default the question is embedded behind an
  instruction, as Qwen3-Embedding is trained to read a question, and the
  chunks with none ("The query instruction"). Why is it declared per index, and
  why did changing it ask the model again and embed no chunk?
- **Exercise 20's answer.** `search.py` put `PLAY-1004`'s `Notes` first for the
  same question, with an instruction of its own. What does that say about how
  much a nearest chunk depends on the wording around the question?

## Task 7 — with tracking on

Start the MLflow server from exercise 08, and add to `.env`:

```
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5000
```

Save this as `read_search_trace.py`:

```python
import json

import mlflow

mlflow.set_tracking_uri("http://127.0.0.1:5000")
experiment = mlflow.get_experiment_by_name("dossier-audit/incident-audit/search")
print("runs   ", len(mlflow.search_runs([experiment.experiment_id], output_format="list")))
traces = mlflow.search_traces(
    locations=[experiment.experiment_id], max_results=2, return_type="list"
)
print("traces ", len(traces), "(the newest two)")
for trace in traces:
    print("trace  ", trace.info.tags.get("mlflow.traceName"), trace.info.state)
    print("  in   ", trace.data.request)
    print("  out  ", trace.data.response)
    for span in trace.data.spans:
        if span.span_type == "EMBEDDING":
            print("  span ", span.span_type, span.attributes["dossier.model"])
            print("       text  ", json.dumps(span.attributes["dossier.text"]))
            print("       cached", span.attributes["dossier.cached"])
            print("       tokens", span.attributes["dossier.tokens"])
        if span.span_type == "RETRIEVER":
            print("  span ", span.span_type, span.name)
            for found in span.attributes["dossier.results"]:
                print("      ", found)
```

```bash
$D search incidents "Why did adding servers make it slower?" --as incident-response --limit 2
$D search incidents "Which incident lost the most money?" --as incident-response --where severity=major --limit 2
$P read_search_trace.py
```

**Checkpoint.** Each search ends `recorded to MLflow:
dossier-audit/incident-audit/search`. The script prints `runs 0` and two
traces named `search incidents`. Each has the question, the filters and the
readers as its request, and the note ids as its response; an `EMBEDDING` span
with the text embedded, instruction and all; and a `RETRIEVER` span with each
result's rank, chunk id, score and two ranks. The first question was asked in
task 6, so its span says `cached True` and `tokens 0`. The second lists
`PLAY-1004`, which lost `CHF 9'900`, above `PLAY-1001`, which lost `CHF
18'400`.

- **No run.** `sync`, `run`, `eval` and `embed` each record an MLflow run. Why
  does a search record a trace and no run (R11.35)?
- **Ids, not text.** The `RETRIEVER` span names chunks by id. Where is their
  text, and why is it not copied into MLflow?
- **The most money.** The search was asked which incident lost the most, and
  put the smaller loss first. What can a ranking by nearness not do that this
  question needs? Which part of `dossier` already holds every note's
  `loss_amount`, as a number?

## Task 8 — how well does it rank?

Every search so far was read by eye. `dossier search INDEX --gold DIR` measures
it instead, against questions a person judged (spec 022). Write one YAML file
per question in `gold/incidents-search/`, grading each note you judged: `2`
answers it, `1` is related, `0` is not relevant. A note you leave out is
unjudged, and counts as not relevant.

```yaml
# gold/incidents-search/an-outage-caused-by-a-configuration-change.yaml
query: an outage caused by a configuration change
readers: [incident-response]
judged_by: you
judged:
  incidents-manual:PLAY-1003.md: 2
  incidents-manual:PLAY-1001.md: 1
  incidents-manual:PLAY-1004.md: 0
  incidents-manual:PLAY-1002.md: 0
```

Write three more: a question about the checkout 504s, one about a job that
missed its window, and the key `PLAY-1004`. Then:

```bash
$D search incidents --gold gold/incidents-search
$D search incidents --gold gold/incidents-search --candidates 1000
$D search incidents --gold gold/incidents-search --words any
Q "select count(*) filter (where text_search @@ websearch_to_tsquery('simple',
   'an outage caused by a configuration change')) as every_word,
   count(*) filter (where text_search @@ websearch_to_tsquery('simple',
   'an or outage or caused or by or a or configuration or change')) as any_word
   from dossier_index.chunks"
```

- Every question probably scores 1.000. What does that say about search, and
  what does it say about four notes?
- What do the unjudged counts tell you, and which notes would you judge next?
- Why do `--candidates 1000` and `--words any` change nothing here? What do the
  two counts from `Q` say would change on two thousand notes?
- With task 7's tracking on, what lands in MLflow, and what do the four
  questions' traces sit under?

---

## Done when

- you can say why a search names the readers it is for, and what it does when
  it names none;
- you can read a search's output, and say why each note is listed and at which
  section;
- you can work out a score from its two ranks, and say what decides a tie;
- you have seen a key found by words, and a question found by meaning alone;
- you know what `--where` matches and what it refuses, and that the refusals
  ask the model nothing;
- you can say what a search writes, what it says about notes the index has not
  seen, and what it records in MLflow;
- you have measured search against your own judgments, and can say why four
  notes cannot decide spec 019's open questions.

## Cleaning up

```bash
Q "delete from dossier_index.chunks where index = 'incidents'"
Q "delete from dossier_index.documents where index = 'incidents'"
rm -rf playground/work/21                                # from the repository root
docker compose -f dev/index/docker-compose.yml down      # keeps the data; down -v drops it
```

**Back to:** [the playground index](../README.md).
