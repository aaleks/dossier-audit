# 20 · Solution

Every command below was run in order, in one pass, on 2026-10-01, at the commit
of `main` that made an `embed` an MLflow run (R11.33, #657). The pass was on
Windows, so `$D` was the worktree's `.venv/Scripts/dossier.exe` and `$P` its
`.venv/Scripts/python.exe`, and `DOSSIER_INDEX_DSN` was set in the shell rather
than in `.env`. Blocks not printed by a command are marked **[derived]**: worked
out from the code or the spec.

The workspace was a copy of an exercise 05 workspace whose latest run,
`20260929T203841Z-6a9a`, was made with task 2's prompt. A real
`openai:gpt-5.4-mini` made that run, not the stub, but its answers to the two
fields this exercise carries match the stub's `replies.json` word for word. The
index's tables held rows from an earlier check, and they were emptied first, so
the pass started where yours does.

What will differ in yours: every timing, the run id, the MLflow run names, and
the distances in task 3, in the last digit or two. The model was already in
memory when the first build started. The spec's first build, the model's load
included, took 76 seconds.

---

## Task 1 — declare and build

```yaml
sources:
  - id: incidents-manual
    type: folder
    path: inbox/incidents/
    acl: [incident-response]
```

```yaml
# indexes/incidents.yaml
pipeline: incident-audit
embedding_model: ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
chunker: {name: headings, max_chars: 2000}
target: {dsn_env: DOSSIER_INDEX_DSN}
```

```console
$ time $D embed incidents
incidents · 21 chunks · 21 embedded · 0 cached · 4 written · 0 removed

real	1m0.985s

$ time $D embed incidents
incidents · 21 chunks · 0 embedded · 21 cached · 0 written · 0 removed

real	0m1.483s

$ find .dossier/cache/embed -type f | wc -l
42
$ cat .dossier/cache/embed/09/8c/098c1111279ef5a653540392e8e09fbb38c30c4ff75b2613acde1843d14deb16.meta.json
{
  "dimensions": 2560,
  "embedding_model": "ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
}
```

**What `written` counts.** Documents. A document's row and all its chunk rows
are written together, and only when the hash of everything they say has moved:
the snapshot, the title, the readers, the chunk ids, headings and texts, the run
and its values. The vectors are left out of that hash, because they are the
pinned model's answer to texts the hash already covers. The second `embed` read
and cut every note again, and each one came to the hash the index already held,
so nothing was written (R18.4 row 1).

**Where the vectors were.** In the workspace: 21 vectors, a file and its
`.meta.json` each, under the key of the pinned model and the text embedded
(R18.3). The snapshot, the document and the index are not in that key. A vector
is the model's answer to a text, whoever files it, so a second index over the
same notes, pinning the same model, asks for nothing (R18.3 row 4).

**Why a file of its own.** A pipeline's version is made from its hash (spec
013). Declared in `pipeline.yaml`, an index would change the hash and the
version of a pipeline whose prompts, schemas and model had not changed. A
comparison across that change would then show two versions with the same
answers. The index reads the pipeline, so it names the pipeline, and the
dependency points only one way.

## Task 2 — look at what was written

```console
$ Q "select key, title, acl, run_id, filter_values from dossier_index.documents
     where index = 'incidents' order by key"
     key      |                                title                                 |         acl         | run_id | filter_values
--------------+----------------------------------------------------------------------+---------------------+--------+---------------
 PLAY-1001.md | PLAY-1001 — Checkout timeouts after the payment gateway upgrade      | {incident-response} |        | {}
 PLAY-1002.md | PLAY-1002 — Nightly export missed the reporting window               | {incident-response} |        | {}
 PLAY-1003.md | PLAY-1003 — Warehouse terminals offline after a firewall rule change | {incident-response} |        | {}
 PLAY-1004.md | PLAY-1004 — Search latency spike during the spring campaign          | {incident-response} |        | {}
(4 rows)

$ Q "select d.key, c.chunk_index, c.kind, c.heading_path, length(c.text) as chars, c.acl
     from dossier_index.chunks c join dossier_index.documents d using (index, document_id)
     where c.index = 'incidents' order by d.key, c.chunk_index"
     key      | chunk_index | kind |                                     heading_path                                      | chars |         acl
--------------+-------------+------+---------------------------------------------------------------------------------------+-------+---------------------
 PLAY-1001.md |           0 | body | {"PLAY-1001 — Checkout timeouts after the payment gateway upgrade"}                   |    97 | {incident-response}
 PLAY-1001.md |           1 | body | {"PLAY-1001 — Checkout timeouts after the payment gateway upgrade",Timeline}          |   498 | {incident-response}
 PLAY-1001.md |           2 | body | {"PLAY-1001 — Checkout timeouts after the payment gateway upgrade","Root cause"}      |   265 | {incident-response}
 PLAY-1001.md |           3 | body | {"PLAY-1001 — Checkout timeouts after the payment gateway upgrade",Impact}            |   106 | {incident-response}
 PLAY-1001.md |           4 | body | {"PLAY-1001 — Checkout timeouts after the payment gateway upgrade",Follow-up}         |   148 | {incident-response}
 […ten rows of PLAY-1002 and PLAY-1003, five each]
 PLAY-1004.md |           0 | body | {"PLAY-1004 — Search latency spike during the spring campaign"}                       |    94 | {incident-response}
 PLAY-1004.md |           1 | body | {"PLAY-1004 — Search latency spike during the spring campaign",Timeline}              |   486 | {incident-response}
 PLAY-1004.md |           2 | body | {"PLAY-1004 — Search latency spike during the spring campaign","Root cause"}          |   195 | {incident-response}
 PLAY-1004.md |           3 | body | {"PLAY-1004 — Search latency spike during the spring campaign",Impact}                |   128 | {incident-response}
 PLAY-1004.md |           4 | body | {"PLAY-1004 — Search latency spike during the spring campaign",Notes}                 |   189 | {incident-response}
 PLAY-1004.md |           5 | body | {"PLAY-1004 — Search latency spike during the spring campaign",Follow-up}             |   124 | {incident-response}
(21 rows)

$ Q "select text from dossier_index.chunks
     where index = 'incidents' and document_id = 'incidents-manual:PLAY-1001.md'
     and chunk_index in (0, 3) order by chunk_index"
                                     text
-------------------------------------------------------------------------------
 **Severity:** major                                                          +
 **Resolved:** 2026-03-04                                                     +
 **Systems affected:** checkout-api, payments-gateway
 Finance reconciled 214 abandoned baskets against the gateway's own records, a+
 recorded loss of CHF 18'400.
(2 rows)

$ Q "select format_type(atttypid, atttypmod) as embedding_type from pg_attribute
     where attrelid = 'dossier_index.chunks'::regclass and attname = 'embedding'"
 embedding_type
----------------
 halfvec(2560)
(1 row)

$ Q "select indexdef from pg_indexes where indexname = 'chunks_embedding'"
                                            indexdef
-------------------------------------------------------------------------------------------------
 CREATE INDEX chunks_embedding ON dossier_index.chunks USING hnsw (embedding halfvec_cosine_ops)
(1 row)

$ Q "select text_search from dossier_index.chunks
     where index = 'incidents' and document_id = 'incidents-manual:PLAY-1001.md'
     and chunk_index = 3"
                                                                                        text_search
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 '18':17 '214':3 '400':18 'a':12 'abandoned':4 'baskets':5 'chf':16 'finance':1 'gateway':8 'loss':14 'of':15 'own':10 'reconciled':2 'recorded':13 'records':11 's':9 'the':7
(1 row)
```

**The headings.** A heading is not in any chunk's text. It is in the chunk's
heading path, every heading above it from the title down, and chunk 0 is the
text between the title and the first `##`. The vector, though, is of the
heading path and then the text (R18.3). **[derived]** For the impact chunk,
that is:

```
PLAY-1001 — Checkout timeouts after the payment gateway upgrade > Impact

Finance reconciled 214 abandoned baskets against the gateway's own records, a
recorded loss of CHF 18'400.
```

The text alone is a sentence about money that names no incident. Embedded with
its headings, it is the checkout incident's impact, and a question about the
checkout incident's cost finds it (R18.1 row 1).

**The column.** pgvector's HNSW index takes a `vector` of up to 2,000
dimensions and a `halfvec` of up to 4,000. Qwen3-Embedding-4B answers 2,560, so
`halfvec(2560)`, by cosine distance (R18.5 row 1). A model answering 1,024 would
be `vector(1024)`. One answering 4,001 is refused, because no pgvector type
indexes it (row 4).

**The readers.** The search that reads this index, not `dossier`. `dossier`
writes who may read each row and never reads the index to answer anyone. So the
system reading it, through a view or a query like task 3's, is the one that
must filter on `acl` (R18.6, "Decisions"). It is on every chunk row because a
search returns chunks, and so it can filter them without a join.

**The words.** `simple` splits at anything that is not a letter or a digit and
lowercases. So `CHF 18'400` is the words `chf`, `18` and `400`, and `gateway's`
is `gateway` and `s`. It does not stem, and it drops no stop word: `reconciled`,
`a`, `of` and `the` are all kept. `english`, on the same chunk:

```console
$ Q "select to_tsvector('english', text) from dossier_index.chunks
     where index = 'incidents' and document_id = 'incidents-manual:PLAY-1001.md'
     and chunk_index = 3"
                                                      to_tsvector
-----------------------------------------------------------------------------------------------------------------------
 '18':17 '214':3 '400':18 'abandon':4 'basket':5 'chf':16 'financ':1 'gateway':8 'loss':14 'reconcil':2 'record':11,13
(1 row)
```

That is better for English and worse for any other language: the notes
`dossier` is meant for are written in more than one, and an English stemmer
mangles a German word ("What it writes").

## Task 3 — search it two ways

**By words.**

```console
$ Q "… plainto_tsquery('simple', 'warehouse') …"
     key      |  section
--------------+------------
 PLAY-1002.md | Timeline
 PLAY-1002.md | Root cause
 PLAY-1002.md | Follow-up
(3 rows)

$ Q "… plainto_tsquery('simple', 'timeout') …"
     key      |  section
--------------+------------
 PLAY-1001.md | Timeline
 PLAY-1001.md | Root cause
(2 rows)

$ Q "… plainto_tsquery('simple', 'timeouts') …"
     key      |  section
--------------+-----------
 PLAY-1001.md | Follow-up
(1 row)

$ Q "… plainto_tsquery('simple', 'autoscaler') …"
     key      | section
--------------+---------
 PLAY-1004.md | Notes
(1 row)

$ Q "… plainto_tsquery('simple', 'warehouse outage cost') …"
 key | section
-----+---------
(0 rows)
```

**By meaning.**

```console
$ $P search.py "How much did the warehouse outage cost?"
0.326  PLAY-1003.md  Impact  'Picking stopped for 77 minutes across two warehouses. The de'
0.393  PLAY-1003.md  PLAY-1003 — Warehouse terminals offline after a firewall rule change  '**Severity:** critical\n**Resolved:** 2026-04-07\n**Systems af'
0.423  PLAY-1002.md  Impact  'No customer-facing impact. Two internal dashboards were a da'

$ $P search.py "Why did adding servers make it slower?"
0.459  PLAY-1004.md  Notes  'The traffic itself was within the capacity the campaign was '
0.463  PLAY-1004.md  Root cause  'Each pod rebuilt the catalogue index locally at start-up, so'
0.484  PLAY-1004.md  Timeline  '- 2026-05-11 18:30 UTC — the spring campaign launches and se'

$ $P search.py "Which incident was caused by a misconfigured autoscaler?"
0.350  PLAY-1004.md  Notes  'The traffic itself was within the capacity the campaign was '
0.447  PLAY-1004.md  Timeline  '- 2026-05-11 18:30 UTC — the spring campaign launches and se'
0.452  PLAY-1002.md  Impact  'No customer-facing impact. Two internal dashboards were a da'
```

Each search by meaning took about two seconds, with the model in memory.

**Missing the warehouse incident.** Two causes. `PLAY-1003`'s text says
`warehouses`, and `simple` does not stem, so `warehouse` is another word. That is
`simple`'s. Its title says `Warehouse`, but a title is a heading, and
`text_search` is a tsvector of the chunk's `text` alone. That is what
`text_search` is made of. The heading path is embedded, so a search by meaning
sees it (R18.3), and a search by words never does. `PLAY-1002` says `warehouse
load` three times, and has nothing to do with warehouses. `timeouts` is the
same story: `PLAY-1001`'s title is not in any `text`, its follow-up says
`timeouts`, and its timeline and root cause say `timeout`.

**The other way round.** `PLAY-1004`'s `Notes` says the autoscaler "reacted as
configured; nothing in this incident points to a misconfigured autoscaler". It
answers the question *no*, and it is the nearest chunk. A distance measures how
near two texts are in what they are about. A passage denying a cause is about
that cause. So nearness cannot tell an answer from its denial, and a search by
words cannot either: `autoscaler` finds the same chunk. A reader of the index
needs something that reads the passage before it calls the first one an answer:
a person, a reranker, or a model asked whether it answers. That is the search
side, and `dossier search` is a later spec. The slowness question shows it too.
The root cause, which is the answer, comes second, behind the note that
discusses scaling without explaining anything.

**The instruction.** Qwen3-Embedding is trained to read a query that says what
it is for, and a document that does not. The chunks are embedded once, for
every question anyone will ask. An instruction baked into them would fix one
kind of question, and changing it would embed every chunk again. So documents
are embedded as they are, and the question's wording, instruction included, is
whoever asks it ("Left out on purpose").

**The `where`.** Here, nothing changes: every row holds `{incident-response}`.
In an index that also read a source declaring `acl: [finance]`, its chunks
would appear in these results without it. `dossier` writes the readers and
enforces nothing at read time. The query does.

## Task 4 — carry the run's record

```yaml
fields:
  filter: [severity, affected_systems]
```

```console
$ $D embed incidents
incidents · 21 chunks · 0 embedded · 21 cached · 4 written · 0 removed

$ Q "select key, run_id, filter_values from dossier_index.documents
     where index = 'incidents' order by key"
     key      |        run_id         |                                  filter_values
--------------+-----------------------+----------------------------------------------------------------------------------
 PLAY-1001.md | 20260929T203841Z-6a9a | {"severity": "major", "affected_systems": "checkout-api, payments-gateway"}
 PLAY-1002.md | 20260929T203841Z-6a9a | {"severity": "minor", "affected_systems": "reporting-export"}
 PLAY-1003.md | 20260929T203841Z-6a9a | {"severity": "critical", "affected_systems": "terminal-gateway, inventory-sync"}
 PLAY-1004.md | 20260929T203841Z-6a9a | {"severity": "major", "affected_systems": "search-api, catalogue-index"}
(4 rows)

$ Q "select key from dossier_index.documents
     where index = 'incidents' and filter_values ->> 'severity' = 'major' order by key"
     key
--------------
 PLAY-1001.md
 PLAY-1004.md
(2 rows)
```

**Written, not embedded.** Each document's row gained a run id and two values,
so the hash of what it says moved, and its rows were written again (R18.4). No
chunk's text moved, so no vector did. A category is never embedded: it is
exact, and a vector would only blur it.

**Only what was grounded.** Every value's span is a line of its note's header,
such as `**Severity:** critical`, found verbatim. A value whose span is not in
the note would have been left out, and `embed` would have said so before its
count: `PLAY-1003.md: 1 value left out: ungrounded`. Eval scores such a value
incorrect whatever it says (R7.4). Carried, it would let a filter return a
category the note does not support, even on the days it happens to be right
(R18.9 row 3).

**No record chunk.** A record chunk holds the run's `free_text` answers, named
in `fields.embed`, as `field: value` lines (R18.9 row 2). `incident.yaml` has no
`free_text` field. One must name a judge, and is withheld from eval until the
judge is calibrated, which is exercise 07, and its comment says so.

**A system to filter on.** `affected_systems` is a `reference`, so the run
answered it as one string, `"checkout-api, payments-gateway"`. An exact filter
for `payments-gateway` matches nothing, and `like '%payments-gateway%'` would
also match a `payments-gateway-v2`. Declared `list`, it would be answered one
record per system (exercise 19). **[derived]** Two or more grounded values are
carried as a JSON array, which `filter_values -> 'affected_systems' ?
'payments-gateway'` tests exactly. One value is carried as a plain string, which
`?` tests just the same.

**`MAJOR`. [derived]** This pass's run answered `major`. Given exercise 05's
task 3 answer instead, the two calls `embed` makes, the check and then
`carried`, pass it and carry `MAJOR` as written:

```python
from dossier.domain.grounding import check_field
from dossier.domain.index import IndexFields, carried
from dossier.domain.schemas import FieldRecord

text = open(".dossier/snapshots/6b/db/6bdb8cad3ebd2dcf76a24acdf1d36b55a5cda49f0a7222c9809044573892b1d0", encoding="utf-8").read()
record = FieldRecord(field="severity", value="MAJOR", confidence="high",
                     source={"document": "PLAY-1001.md", "span": "**Severity:** major"})
check = check_field(record, input_documents={"PLAY-1001.md": text},
                    enums={"severity": ["minor", "major", "critical"]})
print(check.verdict)
print(carried(IndexFields(filter=("severity",)), [(record, check.verdict)]).values)
```

```
FieldVerdict.VALID
{'severity': 'MAJOR'}
```

An `enum` value is checked against the declared values case-folded, as eval
compares it (R6.26), which is why eval scored it correct in exercise 05. But
what is carried is the run's spelling, not the declaration's. So `= 'major'`
finds `PLAY-1004` alone, and only `lower(filter_values ->> 'severity')` finds
both. Spec 018 does not say which spelling a carried category takes. Whether it
should be the declared one is a question for an amendment to R18.9, not for
this exercise.

## Task 5 — change a note after the run

```console
$ echo "- Keep decommissioned ranges in the inventory, marked as retired, so a change can be checked against them." \
    >> inbox/incidents/PLAY-1003.md
$ $D sync incident-audit
incidents-manual  4 known · 1 changed · 0 new -> 4 fetched
      PLAY-1003.md  9c5d76c1930794d25fd2bb6356a7a4f800ae1f5f9c22ba98b81aec45b67769d4 -> 0959a218e3f658dc5052a361e47f0815dacd1d02c1501fe2e67621b0e53f402c
ledger updated · 1 new snapshots · 0 tombstoned

$ time $D embed incidents
PLAY-1003.md: record stale: 20260929T203841Z-6a9a read an earlier snapshot
incidents · 21 chunks · 1 embedded · 20 cached · 1 written · 0 removed

real	0m5.384s

$ Q "select key, left(snapshot, 12) as snapshot, run_id, filter_values
     from dossier_index.documents where index = 'incidents' order by key"
     key      |   snapshot   |        run_id         |                                filter_values
--------------+--------------+-----------------------+-----------------------------------------------------------------------------
 PLAY-1001.md | 6bdb8cad3ebd | 20260929T203841Z-6a9a | {"severity": "major", "affected_systems": "checkout-api, payments-gateway"}
 PLAY-1002.md | 950d8ed7fbe3 | 20260929T203841Z-6a9a | {"severity": "minor", "affected_systems": "reporting-export"}
 PLAY-1003.md | 0959a218e3f6 |                       | {}
 PLAY-1004.md | d7c5317a2393 | 20260929T203841Z-6a9a | {"severity": "major", "affected_systems": "search-api, catalogue-index"}
(4 rows)

$ Q "select chunk_index, heading_path[cardinality(heading_path)] as section,
     left(chunk_id, 12) as chunk_id, length(text) as chars from dossier_index.chunks
     where index = 'incidents' and document_id = 'incidents-manual:PLAY-1003.md'
     order by chunk_index"
 chunk_index |                               section                                |   chunk_id   | chars
-------------+----------------------------------------------------------------------+--------------+-------
           0 | PLAY-1003 — Warehouse terminals offline after a firewall rule change | 6f687b6220a7 |   102
           1 | Timeline                                                             | fe5083125dc6 |   416
           2 | Root cause                                                           | dba99b14d949 |   258
           3 | Impact                                                               | 72e9006d6f72 |   123
           4 | Follow-up                                                            | 33b8ee6ff086 |   252
(5 rows)
```

**Still true, and dropped.** The run's answers describe the snapshot it read,
`9c5d76c1…`. The ledger now holds `0959a218…`, and nothing short of reading the
new note can say whether an edit touched an answer. Here it did not. A note
whose severity was raised from `major` to `critical` would look exactly the
same to `embed`: a new snapshot, an old run. Carrying the old answers would
attach them to text the run never read (R18.8 row 2). What would keep them is a
run over the new snapshot, which is the next bullet.

**One vector.** The follow-up chunk, now 252 characters, was 145. The four
chunks above it embed the same heading path and text as before, so their
vectors were in the cache (R18.3 row 2). `1 written` is `PLAY-1003`'s rows: a
new snapshot, no run, no values, and a new last chunk.

**Getting it back.** A run that reads the new snapshot: `dossier run
incident-audit` (the stub's rule for `PLAY-1003` matches on its heading, and its
spans are all still in the note), then `dossier embed incidents`. The row would
name the new run (R18.11 row 3). Not run in this pass, because task 7 needs a
stale note.

## Task 6 — refusals

```console
$ $D embed incidents; echo "exit $?"          # no acl: line
incidents.yaml: incident-audit reads 'incidents-manual', which declares no readers. Add `acl: [<who may read it>]` to it in sources.yaml: nothing is indexed before someone decides who may search it
exit 2

$ $D embed incidents; echo "exit $?"          # acl: []
sources.yaml, line 10: in 'incidents-manual', 'acl' -- Value error, acl: an empty list names no reader, and is not a decision about who may read this source. Name who may, as acl: [incident-response]
exit 2

$ $D embed incidents; echo "exit $?"          # filter: [severity, root_cause]
incidents.yaml, line 6: fields.filter names 'root_cause', which schemas/incident.yaml does not declare. It declares: affected_systems, loss_amount, resolution_date, severity
exit 2

$ $D embed incidents; echo "exit $?"          # filter: [severity], embed: [affected_systems]
incidents.yaml, line 7: fields.embed names 'affected_systems', a reference field: a category is filtered, not embedded
exit 2

$ $D embed incidents; echo "exit $?"          # embedding_model: ollama:qwen3-embedding:4b-fp16
incidents.yaml, line 3: embedding_model 'ollama:qwen3-embedding:4b-fp16' is an Ollama tag with no digest, and a tag moves when the model is re-pulled. Pin it as 'ollama:<name>:<tag>@sha256:<digest>'
exit 2

$ $D embed incidents; echo "exit $?"          # DOSSIER_INDEX_DSN unset
DOSSIER_INDEX_DSN is not set: it holds the connection string of the index incidents is written to. Set it on this machine, in the shell or in .env, such as postgresql://dossier:<password>@127.0.0.1:5435/dossier
exit 2

$ $D embed incidents; echo "exit $?"          # the password is wrong
preparing index 'incidents' failed: connection failed: connection to server at "127.0.0.1", port 5435 failed: FATAL: password authentication failed for user "dossier"
exit 1
```

With the `acl` put back, `embed` printed what it had before the change:
`PLAY-1003.md: record stale: …` and `0 embedded · 21 cached · 0 written · 0
removed`. The index declaration was copied back from a saved copy after each of
its three changes, and `diff` found nothing between them.

**Before anything.** Every one of the five is a fact about the workspace, and
each is checked before a note is converted, a vector is asked for or a row is
written. Found after the first build, a missing connection string would have
cost a minute of a CPU and 8 GB of RAM for vectors with nowhere to go. They
would be cached, so not lost, but nobody would have chosen to wait for that
(R18.7 row 3).

**`acl: []`.** An empty list is what someone types while they decide, and what
a template leaves behind. Read as "nobody", it would build an index nobody can
search, silently. Read as "everybody", it would open the index to everyone.
Neither is a decision anyone made, so both a missing `acl` and an empty one are
refused, and the message names the key to write (R18.6 rows 2 and 3). The empty
list is refused by the source's own validation, so `sync` refuses it too. A
missing `acl` is a matter only for an index that reads the source.

**The wrong list.** `root_cause` is not declared here, so the refusal lists
what is. In a schema declaring it `free_text`, it would be refused as free text
in `filter` (R18.10 row 2). Free text is prose, two answers almost never match
character for character, and an exact filter on it finds nothing. So it is
embedded, in the record chunk, where a search by meaning can find it.
`affected_systems` is the mirror case: a category is exact, and a vector would
only blur it (R18.10 row 3).

**A tag.** The tag is in no vector's key, and the digest is. Re-pulled under
the same tag, a new model would answer new vectors for new chunks and the old
ones would stay cached, so one index would hold vectors of two models that are
not comparable. Every search would then compare a question's vector against both,
and not say so. Pinned by digest, a new model is a new pin: every chunk is
embedded again, and the vectors stay of one model (R18.10 row 4, R18.3 row 3,
R9.3).

**2 and 1.** Exit `2` is a mistake in the workspace, refused before any work,
and it says what to change. Exit `1` is the workspace being right and a server
answering with an error: the index's Postgres here, and the same holds for
Ollama. Whatever was cached before the failure stays cached for the next
`embed`.

## Task 7 — with tracking on

```console
$ echo "- Alert when the pool hands out a socket the balancer has already closed." \
    >> inbox/incidents/PLAY-1001.md
$ $D sync incident-audit
incidents-manual  4 known · 1 changed · 0 new -> 4 fetched
      PLAY-1001.md  6bdb8cad3ebd2dcf76a24acdf1d36b55a5cda49f0a7222c9809044573892b1d0 -> 949c99289ee8d774f112a794e733e30c12bf23377a246a6daa8824f5d7dac319
ledger updated · 1 new snapshots · 0 tombstoned
recorded to MLflow: dossier-audit/incident-audit/sync

$ $D embed incidents
PLAY-1001.md: record stale: 20260929T203841Z-6a9a read an earlier snapshot
PLAY-1003.md: record stale: 20260929T203841Z-6a9a read an earlier snapshot
incidents · 21 chunks · 1 embedded · 20 cached · 1 written · 0 removed
recorded to MLflow: dossier-audit/incident-audit/embed
2026/10/01 11:46:43 INFO mlflow.tracing.export.async_export_queue: Flushing the async trace logging queue before program exit. This may take a while...

$ $P read_embed_run.py
embed incidents 20261001T094634Z FINISHED
tags    {'dossier.kind': 'embed', 'dossier.pipeline': 'incident-audit'}
params  {'index': 'incidents', 'embedding_model': 'ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc', 'dossier_version': '0.1.0'}
metrics {'chunks': 21.0, 'embedded': 1.0, 'cached': 20.0, 'written': 1.0, 'removed': 0.0}
trace   embed incidents · request 1 OK
  span  EMBEDDING ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
       chunks ['1c1250170e3a93560de804f13cde636d676a42e80390b2f2c23e9fd22891f2dd']
       tokens 70

$ $D embed incidents
PLAY-1001.md: record stale: 20260929T203841Z-6a9a read an earlier snapshot
PLAY-1003.md: record stale: 20260929T203841Z-6a9a read an earlier snapshot
incidents · 21 chunks · 0 embedded · 21 cached · 0 written · 0 removed

$ Q "delete from dossier_index.documents where index = 'incidents'"
DELETE 4
$ Q "select count(*) from dossier_index.chunks where index = 'incidents'"
 count
-------
     0
(1 row)

$ $D embed incidents
PLAY-1001.md: record stale: 20260929T203841Z-6a9a read an earlier snapshot
PLAY-1003.md: record stale: 20260929T203841Z-6a9a read an earlier snapshot
incidents · 21 chunks · 0 embedded · 21 cached · 4 written · 0 removed
recorded to MLflow: dossier-audit/incident-audit/embed

$ $P read_embed_run.py
embed incidents 20261001T094743Z FINISHED
tags    {'dossier.kind': 'embed', 'dossier.pipeline': 'incident-audit'}
params  {'index': 'incidents', 'embedding_model': 'ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc', 'dossier_version': '0.1.0'}
metrics {'chunks': 21.0, 'embedded': 0.0, 'cached': 21.0, 'written': 4.0, 'removed': 0.0}
```

The run is named by when it started, in UTC: the `embed` started at 11:46 local
time, which was UTC+2. Its experiment is R10.2's default for the pipeline, kind
`embed`.

**What is recorded.** Whether the index changed: an `embed` that wrote or
removed something is a run, and one that changed nothing records nothing, as a
`gc` that found nothing to delete records nothing (R11.33 row 4). The traces are
the requests for vectors, one each, because each is a model call (row 2). The
rebuild after the delete wrote four documents and asked for nothing, so it is a
run with no trace.

**A chunk id.**

```console
$ Q "select d.key, c.heading_path[cardinality(c.heading_path)] as section, c.chunk_id
     from dossier_index.chunks c join dossier_index.documents d using (index, document_id)
     where c.index = 'incidents' and c.chunk_id like '1c125017%'"
     key      |  section  |                             chunk_id
--------------+-----------+------------------------------------------------------------------
 PLAY-1001.md | Follow-up | 1c1250170e3a93560de804f13cde636d676a42e80390b2f2c23e9fd22891f2dd
(1 row)
```

`PLAY-1001`'s follow-up, the section the new line landed in. Its id is the hash
of its document, its chunker and that chunker's settings, its position and its
text (R18.2). The settings are in it, so a chunk cut with `max_chars: 1000` is
another chunk, even where its text comes out the same: a chunk cut under other
settings is another chunk (R18.2 row 3, R0.5). The span names ids, not text,
because the text is in the index and in the snapshot already, and a trace that
copied every chunk would put the notes in MLflow too.

**Derived data.** Postgres is a projection of the workspace, rebuilt from the
snapshots, their conversions, the run and `.dossier/cache/embed/`, with no
model asked (R18.4 row 5). To make the next `embed` ask again, you would have to
lose the cache, or pin another model.

**The first build. [derived]** One trace. `embed` asks for at most `BATCH = 32`
texts a request, and 21 fit in one. The number is in no rule. It sets how many
requests a first build makes, and nothing else.

## Cleaning up

```console
$ Q "delete from dossier_index.chunks where index = 'incidents'"
DELETE 21
$ Q "delete from dossier_index.documents where index = 'incidents'"
DELETE 4
```
