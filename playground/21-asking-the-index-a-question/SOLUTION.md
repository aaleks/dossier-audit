# 21 · Solution

Every command below was run in order, in one pass, on 2026-10-02, at the commit
of `main` that made a search name its readers (R19.10 to R19.12, #678). A
first pass on 2026-10-01, before that commit, ranked every search the same.
The pass was on Windows, so `$D` was the worktree's
`.venv/Scripts/dossier.exe` and `$P` its `.venv/Scripts/python.exe`, and
`DOSSIER_INDEX_DSN` was set in the shell rather than in `.env`. Blocks not
printed by a command are marked **[derived]**: worked out from the code or the
spec.

The workspace was a copy of an exercise 05 workspace whose latest run is
`20260922T195104Z-96c1`. The index's rows from an earlier check were deleted
first, so the pass started where yours does. The model was loaded once for
the first `embed` and stayed in memory for the rest.

What will differ in yours: the run id, and a rank by meaning wherever two
chunks are nearly as near. The chunk ids, the filters, the refusals and the
counts should be the same.

---

## Setup

```yaml
# indexes/incidents.yaml
pipeline: incident-audit
embedding_model: ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
chunker: {name: headings, max_chars: 2000}
fields:
  filter: [severity, affected_systems]
target: {dsn_env: DOSSIER_INDEX_DSN}
```

```console
$ $D embed incidents
incidents · 21 chunks · 21 embedded · 0 cached · 4 written · 0 removed
```

## Task 1 — ask it a question

```console
$ $D search incidents "How much did the warehouse outage cost?"; echo "exit $?"
name the readers this search is for with --as READER (incident-response), or search every chunk with --all-readers
exit 2

$ $D search incidents "How much did the warehouse outage cost?" --as incident-response
incidents · 4 documents · as incident-response
1. PLAY-1003.md · PLAY-1003 — Warehouse terminals offline after a firewall rule change
   PLAY-1003 — Warehouse terminals offline after a firewall rule change > Impact
   Picking stopped for 77 minutes across two warehouses. The delayed shipments were credited at a recorded loss of CHF 61'250.
   affected_systems: terminal-gateway, inventory-sync · severity: critical
2. PLAY-1002.md · PLAY-1002 — Nightly export missed the reporting window
   PLAY-1002 — Nightly export missed the reporting window > Impact
   No customer-facing impact. Two internal dashboards were a day stale for one business morning. No financial loss was recorded for this incident.
   affected_systems: reporting-export · severity: minor
3. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign > Impact
   Search was degraded for 45 minutes at the campaign's peak. The campaign team recorded a loss of CHF 9'900 in attributed revenue.
   affected_systems: search-api, catalogue-index · severity: major
4. PLAY-1001.md · PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   PLAY-1001 — Checkout timeouts after the payment gateway upgrade > Impact
   Finance reconciled 214 abandoned baskets against the gateway's own records, a recorded loss of CHF 18'400.
   affected_systems: checkout-api, payments-gateway · severity: major

$ $D search incidents "How much did the warehouse outage cost?" --as incident-response --limit 2
incidents · 2 documents · as incident-response
1. PLAY-1003.md · PLAY-1003 — Warehouse terminals offline after a firewall rule change
   PLAY-1003 — Warehouse terminals offline after a firewall rule change > Impact
   Picking stopped for 77 minutes across two warehouses. The delayed shipments were credited at a recorded loss of CHF 61'250.
   affected_systems: terminal-gateway, inventory-sync · severity: critical
2. PLAY-1002.md · PLAY-1002 — Nightly export missed the reporting window
   PLAY-1002 — Nightly export missed the reporting window > Impact
   No customer-facing impact. Two internal dashboards were a day stale for one business morning. No financial loss was recorded for this incident.
   affected_systems: reporting-export · severity: minor
```

Each line is the note, its title, the heading path of its best chunk, that
chunk's text on one line, cut at a word to at most 200 characters, and the
values its run carried (R19.12 row 1).

**Four of four.** A search by meaning orders every chunk by its distance from
the question and takes the nearest 100. Nearest is relative: there is always a
first, however far it is. The fused score is made of ranks, not distances, so
the nearest chunk of an index of unrelated notes scores `1/61`, as the nearest
of a perfect match does. Nothing in a rank says where the answers stop. Saying
so needs a judgement of whether a passage answers, which is the evaluated rule
spec 019 leaves to a later spec ("Left out on purpose", "Measuring relevance").
Until then, `--limit` is how many you are shown, not how many answered.

**Once each.** A note is listed once, at the place of its best chunk, the one
with the highest fused score (R19.2). `PLAY-1003`'s best is its `Impact`, the
nearest chunk of all.

**The second answer.** No. `PLAY-1002`'s impact says no financial loss was
recorded, for another incident. It is about the cost of an incident, which is
what the question is about, so it is near. As with the autoscaler in exercise
20, nearness cannot tell an answer from a passage on the same subject that
answers something else.

**No reader.** Whatever holds the connection string: `dossier search`, a
person or an agent searching on someone's behalf. The string reads every row,
by SQL as exercise 20 did, so Postgres keeps no reader out, and the search does
it, with `--as`, on every chunk's readers. Postgres could, with a role per
reader, but those roles cannot be managed where `dossier` runs ("Decisions",
"Left out on purpose"). So a search names the readers it is for. One that
names none would list every chunk, whoever it was for, and an agent that forgot
the flag would show someone everything. It is refused before the model is
asked, and searching everything is a flag of its own, `--all-readers` (task 4,
R19.11).

## Task 2 — two lists, one order

```console
$ $D search incidents "How much did the warehouse outage cost?" --as incident-response --json --limit 2
{
  "index": "incidents",
  "query": "How much did the warehouse outage cost?",
  "readers": [
    "incident-response"
  ],
  "results": [
    {
      "rank": 1,
      "document_id": "incidents-manual:PLAY-1003.md",
      "title": "PLAY-1003 — Warehouse terminals offline after a firewall rule change",
      "values": {
        "severity": "critical",
        "affected_systems": "terminal-gateway, inventory-sync"
      },
      "chunk_id": "72e9006d6f72ba11270609df277921e632f427594827b4d464e9f3d3af750d86",
      "kind": "body",
      "heading_path": [
        "PLAY-1003 — Warehouse terminals offline after a firewall rule change",
        "Impact"
      ],
      "text": "Picking stopped for 77 minutes across two warehouses. The delayed shipments were\ncredited at a recorded loss of CHF 61'250.",
      "score": 0.01639344262295082,
      "meaning_rank": 1,
      "words_rank": null
    },
    {
      "rank": 2,
      "document_id": "incidents-manual:PLAY-1002.md",
      "title": "PLAY-1002 — Nightly export missed the reporting window",
      "values": {
        "severity": "minor",
        "affected_systems": "reporting-export"
      },
      "chunk_id": "9101711a76be1fa9481b9228c99914abd60b8bcef0f637ab6cc031e82d28708c",
      "kind": "body",
      "heading_path": [
        "PLAY-1002 — Nightly export missed the reporting window",
        "Impact"
      ],
      "text": "No customer-facing impact. Two internal dashboards were a day stale for one\nbusiness morning. No financial loss was recorded for this incident.",
      "score": 0.015873015873015872,
      "meaning_rank": 3,
      "words_rank": null
    }
  ],
  "unreflected": 0
}

$ $D search incidents "How much did the warehouse outage cost?" --as incident-response --json --limit 2 | $P ranks.py
1 PLAY-1003.md Impact                   0.016393 meaning 1 words None
2 PLAY-1002.md Impact                   0.015873 meaning 3 words None

$ $D search incidents "warehouse" --as incident-response --json --limit 3 | $P ranks.py
1 PLAY-1002.md Follow-up                0.032266 meaning 3 words 1
2 PLAY-1003.md Impact                   0.032018 meaning 1 words 4
3 PLAY-1001.md Impact                   0.014085 meaning 11 words None

$ $D search incidents "warehouse or cost" --as incident-response --json --limit 3 | $P ranks.py
1 PLAY-1002.md Follow-up                0.032018 meaning 4 words 1
2 PLAY-1003.md Impact                   0.032018 meaning 1 words 4
3 PLAY-1001.md Impact                   0.014706 meaning 8 words None

$ $D search incidents "PLAY-1004" --as incident-response --limit 2
incidents · 2 documents · as incident-response
1. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign
   **Severity:** major **Resolved:** 2026-05-12 **Systems affected:** search-api, catalogue-index
   affected_systems: search-api, catalogue-index · severity: major
2. PLAY-1002.md · PLAY-1002 — Nightly export missed the reporting window
   PLAY-1002 — Nightly export missed the reporting window > Impact
   No customer-facing impact. Two internal dashboards were a day stale for one business morning. No financial loss was recorded for this incident.
   affected_systems: reporting-export · severity: minor

$ Q "… websearch_to_tsquery('simple', 'warehouse') …"
     key      |                               section                                | words |  chunk
--------------+----------------------------------------------------------------------+-------+----------
 PLAY-1002.md | Follow-up                                                            |   0.1 | 0d67bd5e
 PLAY-1002.md | Root cause                                                           |   0.1 | 219f781a
 PLAY-1003.md | PLAY-1003 — Warehouse terminals offline after a firewall rule change |   0.1 | 6f687b62
 PLAY-1003.md | Impact                                                               |   0.1 | 72e9006d
 PLAY-1003.md | Follow-up                                                            |   0.1 | c8f8baf4
 PLAY-1002.md | Timeline                                                             |   0.1 | d03dc0bf
 PLAY-1003.md | Root cause                                                           |   0.1 | dba99b14
 PLAY-1003.md | Timeline                                                             |   0.1 | fe508312
(8 rows)

$ Q "select websearch_to_tsquery('simple', 'How much did the warehouse outage cost?'),
            websearch_to_tsquery('simple', 'warehouse or cost')"
                       websearch_to_tsquery                       | websearch_to_tsquery
------------------------------------------------------------------+----------------------
 'how' & 'much' & 'did' & 'the' & 'warehouse' & 'outage' & 'cost' | 'warehouse' | 'cost'
(1 row)
```

**The arithmetic. [derived]** The question: `1/61 = 0.016393` for the nearest
chunk, and `1/63 = 0.015873` for `PLAY-1002`'s impact, third by meaning. The
second nearest was another of `PLAY-1003`'s chunks, so it took no line of its
own. `warehouse`: `1/63 + 1/61 = 0.032266` for `PLAY-1002`'s follow-up, `1/61 +
1/64 = 0.032018` for `PLAY-1003`'s impact, and `1/71 = 0.014085` for a chunk
found by meaning alone, eleventh. A cosine distance runs from 0 to 2, and
`ts_rank_cd` here is `0.1` for every match. Added, the list with the larger
numbers would decide, and the two are on scales that mean different things. A
rank means the same in both lists. The 60 keeps the first few places from
outweighing the rest: first is worth `1/61`, and tenth `1/70` (R19.1, "How a
search ranks").

**Nothing by words.** Every word, `how` and `the` included: `simple` drops no
stop word, and `websearch_to_tsquery` joins words with `&`. `outage` is in no
chunk, and neither is `cost`: the notes say `loss`. One missing word is enough
to match nothing. `or` asked for either word, and `warehouse` matched eight
chunks. A question in plain English carries words a note does not use, so it is
often ranked by meaning alone. That is what a fusion of one list does (R19.12
row 3), and whether any word should do is open question 2.

**The export incident first.** The tie-break. Each of the eight chunks holds
`warehouse` once, `PLAY-1003`'s in its title and `PLAY-1002`'s in `warehouse
load`, and `ts_rank_cd` gives every one `0.1`. The words list is then in chunk
id order, and `0d67bd5e` is `PLAY-1002`'s follow-up. A chunk id is a hash: the
order is the same on every machine and means nothing. Fused, words-first
outweighs `PLAY-1003`'s impact, which is first by meaning and fourth by words.
BM25 would have weighed the rarity of `warehouse` and the length of each chunk,
and is the half of spec 019's rejected option that would have helped here
("Existing options considered"). Over four notes the effect is a coin toss on
ties. Over a real corpus, whether it matters is what "Measuring relevance" is
for.

**A tie.** Under `warehouse or cost` the two have the same two ranks, swapped:
`1/64 + 1/61` and `1/61 + 1/64`. Equal to the last bit. The chunk id decides,
compared as bytes, under the `C` collation in Postgres and as Python compares
strings, so both agree and every machine lists the same order (R19.1 row 3).
Without a rule, Postgres may return equal rows in any order, and the same
search could list two orders on two days.

**A key.** By words. `PLAY-1004` is `'play' <-> '-1004'`, and every chunk of
`PLAY-1004` holds both words, in its heading path, the note's title.
Exercise 20's `text_search` was the chunk's text alone, and the key is in no
text, so no chunk held it, while the vector, made from the heading path and the
text, did. A search for `PLAY-1004` by its own key listed it third. That is
what the live check of spec 019 found, and R19.9 made the words the text the
vector was made from. An index built before R19.9 has its words rebuilt by
its next `embed`, from the rows it holds, with nothing embedded again.

## Task 3 — chunks or documents

```console
$ $D search incidents "firewall rule" --as incident-response --chunks --limit 4
incidents · 4 chunks · as incident-response
1. PLAY-1003.md · PLAY-1003 — Warehouse terminals offline after a firewall rule change
   PLAY-1003 — Warehouse terminals offline after a firewall rule change > Root cause
   A firewall change written against a stale network inventory replaced the allow rule for the active terminal subnet with a rule for a range that had been decommissioned six months earlier, so every…
   affected_systems: terminal-gateway, inventory-sync · severity: critical
2. PLAY-1003.md · PLAY-1003 — Warehouse terminals offline after a firewall rule change
   PLAY-1003 — Warehouse terminals offline after a firewall rule change > Follow-up
   - Fail a firewall change whose subnets are not in the live inventory. - Page on terminal authentication failure rate, not only on gateway health.
   affected_systems: terminal-gateway, inventory-sync · severity: critical
3. PLAY-1003.md · PLAY-1003 — Warehouse terminals offline after a firewall rule change
   PLAY-1003 — Warehouse terminals offline after a firewall rule change > Timeline
   - 2026-04-06 05:48 UTC — every handheld terminal in two warehouses fails to authenticate. Picking stops. - 2026-04-06 06:20 UTC — a firewall change applied overnight is found to have replaced an…
   affected_systems: terminal-gateway, inventory-sync · severity: critical
4. PLAY-1003.md · PLAY-1003 — Warehouse terminals offline after a firewall rule change
   PLAY-1003 — Warehouse terminals offline after a firewall rule change
   **Severity:** critical **Resolved:** 2026-04-07 **Systems affected:** terminal-gateway, inventory-sync
   affected_systems: terminal-gateway, inventory-sync · severity: critical

$ $D search incidents "firewall rule" --as incident-response --limit 4
incidents · 4 documents · as incident-response
1. PLAY-1003.md · PLAY-1003 — Warehouse terminals offline after a firewall rule change
   PLAY-1003 — Warehouse terminals offline after a firewall rule change > Root cause
   A firewall change written against a stale network inventory replaced the allow rule for the active terminal subnet with a rule for a range that had been decommissioned six months earlier, so every…
   affected_systems: terminal-gateway, inventory-sync · severity: critical
2. PLAY-1001.md · PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   PLAY-1001 — Checkout timeouts after the payment gateway upgrade > Timeline
   - 2026-03-02 09:14 UTC — checkout starts returning 504s on about one request in five. The on-call engineer is paged by the synthetic checkout probe. - 2026-03-02 09:41 UTC — the payment gateway…
   affected_systems: checkout-api, payments-gateway · severity: major
3. PLAY-1002.md · PLAY-1002 — Nightly export missed the reporting window
   PLAY-1002 — Nightly export missed the reporting window > Follow-up
   - Trigger the export from the warehouse load's completion event. - Alert when the export has not finished 30 minutes before the window closes.
   affected_systems: reporting-export · severity: minor
4. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign > Notes
   The traffic itself was within the capacity the campaign was planned for. The autoscaler reacted as configured; nothing in this incident points to a misconfigured autoscaler or to an attack.
   affected_systems: search-api, catalogue-index · severity: major
```

**One note fills the list.** `--chunks` lists the fused chunks as they are, so
the one note that is about firewalls took every place. A long runbook would do
the same to every question it touches. A person asking which incidents went
this way wants incidents, so documents are the default, decided when spec 019
was written (R19.2 row 4, "Decisions"). `--chunks` is for reading
every passage of the notes that answer, in the order they answer.

**The same first line.** Yes. A note is listed at the place of its best chunk,
which is the first of its chunks in the fused list `--chunks` prints. Here,
`PLAY-1003`'s root cause both times (R19.2).

**Three more notes.** A search by meaning always has candidates, and nothing
cuts the list by distance (task 1). Their lines say it: a timeline about 504s,
a follow-up about an export and a note about an autoscaler, none of them
naming a firewall. `--json` would show `words_rank: null` on each, found by
meaning alone.

## Task 4 — filters and readers

```console
$ $D search incidents "slow responses for customers" --as incident-response --where severity=MAJOR
incidents · 2 documents · as incident-response
1. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign
   **Severity:** major **Resolved:** 2026-05-12 **Systems affected:** search-api, catalogue-index
   affected_systems: search-api, catalogue-index · severity: major
2. PLAY-1001.md · PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   **Severity:** major **Resolved:** 2026-03-04 **Systems affected:** checkout-api, payments-gateway
   affected_systems: checkout-api, payments-gateway · severity: major

$ $D search incidents "slow responses for customers" --as incident-response --where severity=major --where severity=critical --limit 3
incidents · 3 documents · as incident-response
1. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign
   **Severity:** major **Resolved:** 2026-05-12 **Systems affected:** search-api, catalogue-index
   affected_systems: search-api, catalogue-index · severity: major
2. PLAY-1001.md · PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   **Severity:** major **Resolved:** 2026-03-04 **Systems affected:** checkout-api, payments-gateway
   affected_systems: checkout-api, payments-gateway · severity: major
3. PLAY-1003.md · PLAY-1003 — Warehouse terminals offline after a firewall rule change
   PLAY-1003 — Warehouse terminals offline after a firewall rule change > Impact
   Picking stopped for 77 minutes across two warehouses. The delayed shipments were credited at a recorded loss of CHF 61'250.
   affected_systems: terminal-gateway, inventory-sync · severity: critical

$ $D search incidents "slow responses for customers" --as incident-response --where severity=major \
    --where "affected_systems=search-api, catalogue-index"
incidents · 1 document · as incident-response
1. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign
   **Severity:** major **Resolved:** 2026-05-12 **Systems affected:** search-api, catalogue-index
   affected_systems: search-api, catalogue-index · severity: major

$ $D search incidents "slow responses for customers" --as incident-response --where affected_systems=search-api
incidents · 0 documents · as incident-response
no documents found

$ $D search incidents "slow responses for customers" --all-readers --limit 1
incidents · 1 document · not filtered by reader
1. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign
   **Severity:** major **Resolved:** 2026-05-12 **Systems affected:** search-api, catalogue-index
   affected_systems: search-api, catalogue-index · severity: major

$ V
27
$ $D search incidents "who was paged" --as sre; echo "exit $?"
no source of incident-audit declares sre as a reader; they declare incident-response
exit 2
$ $D search incidents "who was paged" --as incident-response --as sre; echo "exit $?"
no source of incident-audit declares sre as a reader; they declare incident-response
exit 2
$ $D search incidents "who was paged" --as incident-response --all-readers; echo "exit $?"
--as and --all-readers contradict: name the readers, or ask for every chunk
exit 2
$ $D search incidents "who was paged" --as incident-response --where loss_amount=18400; echo "exit $?"
loss_amount is not a filter of incidents; its filters are affected_systems, severity
exit 2
$ $D search incidents "who was paged" --as incident-response --where severity=huge; echo "exit $?"
huge is not a value of severity; it declares critical, major, minor
exit 2
$ V
27
```

27 is the 21 chunks and the six questions asked so far.

**`MAJOR`.** It was folded to `major`, the spelling the declaration writes,
before the index was asked, by the same decision that refuses `huge` (R19.4).
The values are carried in that spelling (R18.9 row 5), so the index compares
exact strings, and one decision in `domain/` both reads and refuses a value,
testable without a database. A case-blind comparison in SQL would have been a
second place deciding what `major` means, and would not have refused `huge`.

**Or, and.** A field holds one value for a note, or a list of them. `severity`
both `major` and `critical` would match no note, so a field given twice can
only usefully mean either. Different fields narrow, as filters do: each one
answers a different question about the note.

**A system.** `affected_systems` is a `reference`, one string a note:
`search-api, catalogue-index`. `--where` matches a whole value, so `search-api`
is a different string. Declared a `list`, as exercise 19 declares one, each
system would be a value of its own, and `search-api` would match ("How a search
ranks", "A filter matches a whole value"). The live check of spec 019 found this
on the same notes.

**Before the model.** Each refusal is decided from the declarations alone: the
index file's filters, the schema's values and the sources' readers. Embedding
first would ask the model, and cache a vector, for a search that cannot run.
So the question was never asked, and `V` did not move (R19.4 rows 5 and 6,
R19.10, R19.11).

**A reader nobody declared.** Alone, an empty answer would read as "nothing is
about that": a mistyped `incident-respnose` would hide every note and say
nothing was found. Beside `incident-response`, ignoring it would narrow the
search without a word, to what the one spelled right may read. Refused, it
names the readers that are declared (R19.10 row 4).

**Two readers.** One list ranks both readers' chunks against each other, by
the same two ranks (task 2). Two searches would each rank their own, and a
first place in one says nothing about a first place in the other, so the merge
would be a guess. And a chunk both may read would come back twice (R19.10).

**Every chunk.** For a person who may read everything, such as whoever runs
`dossier` and holds the connection string, looking across all of it. Never
for a search on someone's behalf. It has to be asked for because the default
is where a forgotten flag lands: had a search with no `--as` listed every
chunk, forgetting would be invisible, and now it is an error (R19.11).

## Task 5 — what the index has not seen

```console
$ $D sync incident-audit
incidents-manual  4 known · 0 changed · 1 new -> 5 fetched
ledger updated · 1 new snapshots · 0 tombstoned

$ $D search incidents "refunds issued twice" --as incident-response --limit 2
incidents · 2 documents · as incident-response
1. PLAY-1001.md · PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   PLAY-1001 — Checkout timeouts after the payment gateway upgrade > Impact
   Finance reconciled 214 abandoned baskets against the gateway's own records, a recorded loss of CHF 18'400.
   affected_systems: checkout-api, payments-gateway · severity: major
2. PLAY-1002.md · PLAY-1002 — Nightly export missed the reporting window
   PLAY-1002 — Nightly export missed the reporting window > Impact
   No customer-facing impact. Two internal dashboards were a day stale for one business morning. No financial loss was recorded for this incident.
   affected_systems: reporting-export · severity: minor
1 held document not in incidents as held: run dossier embed incidents

$ $D embed incidents
PLAY-1005.md: no record: 20260922T195104Z-96c1 did not read it
incidents · 23 chunks · 2 embedded · 21 cached · 1 written · 0 removed

$ $D search incidents "refunds issued twice" --as incident-response --limit 2
incidents · 2 documents · as incident-response
1. PLAY-1005.md · PLAY-1005 — Refunds issued twice after a payment retry
   PLAY-1005 — Refunds issued twice after a payment retry > Impact
   Refunds were issued twice for 31 orders before the retry was stopped.
2. PLAY-1001.md · PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   PLAY-1001 — Checkout timeouts after the payment gateway upgrade > Impact
   Finance reconciled 214 abandoned baskets against the gateway's own records, a recorded loss of CHF 18'400.
   affected_systems: checkout-api, payments-gateway · severity: major

$ rm inbox/incidents/PLAY-1005.md
$ $D sync incident-audit
incidents-manual  5 known · 0 changed · 0 new -> 4 fetched
      PLAY-1005.md  tombstoned
ledger updated · 0 new snapshots · 1 tombstoned

$ $D search incidents "refunds issued twice" --as incident-response --limit 1
incidents · 1 document · as incident-response
1. PLAY-1005.md · PLAY-1005 — Refunds issued twice after a payment retry
   PLAY-1005 — Refunds issued twice after a payment retry > Impact
   Refunds were issued twice for 31 orders before the retry was stopped.
1 held document not in incidents as held: run dossier embed incidents

$ $D embed incidents
incidents · 21 chunks · 0 embedded · 21 cached · 0 written · 1 removed

$ $D search incidents "refunds issued twice" --as incident-response; echo "exit $?"
incidents was embedded with ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc, and is declared with ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bd: run dossier embed incidents
exit 2
```

**Saying so.** A search changes nothing: no row, no file, no cache entry but
the question's vector (R19.3). Embedding a note is `embed`'s work, and it
writes the index. A search answers from what was last embedded, and when the
workspace holds a note the index does not hold as it is, that is the one thing
a ranked list cannot show, so the search counts it, after the results (R19.7).

**A deleted note, found.** The index is derived data, and nothing had derived
it again since the note went. The rows stay until the next `embed` removes
them, so the search can still find them. The count line is the only sign: a
tombstoned note is counted with the new and the changed ones (R19.7 row 3).

**No values.** The latest run did not read `PLAY-1005`: it was synced after the
run. A value is carried only from a run that read the note as the index holds
it, and only where the run grounded it (R18.8, R18.9). Running the pipeline
again, then `embed`, would carry its severity. What the note says is not a
value until a run has extracted it.

**Another model.** The question's vector would come from the declared model,
and every chunk's from the model the index was embedded with. Vectors of two
models are not in one space, so the distances between them would be numbers
that mean nothing, and the ranking would still look like a ranking. Refused
before the question is embedded, naming both (R19.6). Here the declared digest
was the mistake. Had the model really changed, `embed` would build the index
again with it.

## Task 6 — the question's vector

```console
$ V
30
$ $D search incidents "Why did adding servers make it slower?" --as incident-response --json --limit 3 | $P ranks.py
1 PLAY-1004.md Root cause               0.016393 meaning 1 words None
2 PLAY-1001.md Root cause               0.015385 meaning 5 words None
3 PLAY-1003.md PLAY-1003 — Warehouse te 0.014706 meaning 8 words None
$ V
31
$ $D search incidents "Why did adding servers make it slower?" --as incident-response --limit 1
incidents · 1 document · as incident-response
1. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign > Root cause
   Each pod rebuilt the catalogue index locally at start-up, so scaling out under load added pods that served partial results for their first eight minutes and made latency worse rather than better.
   affected_systems: search-api, catalogue-index · severity: major
$ V
31
$ echo 'query_instruction: ""' >> indexes/incidents.yaml
$ $D search incidents "Why did adding servers make it slower?" --as incident-response --json --limit 3 | $P ranks.py
1 PLAY-1004.md Root cause               0.016393 meaning 1 words None
2 PLAY-1001.md Root cause               0.015625 meaning 4 words None
3 PLAY-1003.md PLAY-1003 — Warehouse te 0.014493 meaning 9 words None
$ V
32
```

30 is task 5's two new chunks and its one question added to task 4's 27.

**One more, then none.** Under the pinned model and the exact text embedded,
instruction and all, in the cache's `embed` namespace, beside the chunks'
vectors (R18.3). It is the only thing a search writes (R19.3). It is safe to
write because it is the model's answer to that text and nothing else: the next
search asking the same is answered from it, and no `embed` and no other search
can be changed by it.

**The instruction.** The index is what decides which questions its chunks are
there to answer, so it declares how they are asked, with a default about
incidents ("The query instruction"). The instruction is part of the text
embedded, so it is part of the vector's key: changed, it asked the model once,
for the question's new text. No chunk changed, because the chunks are embedded
with no instruction at all.

**Exercise 20's answer.** Its instruction was another sentence, and it put the
`Notes` section, which denies the cause, ahead of the root cause, which is the
answer. Here, with the default instruction or none, the root cause is first,
and with none, `PLAY-1001`'s rank moved. A few words around a question move
the order of chunks that are nearly as near. Which wording is better can only
be judged against questions a person has answered ("Measuring relevance").

## Task 7 — with tracking on

```console
$ $D search incidents "Why did adding servers make it slower?" --as incident-response --limit 2
incidents · 2 documents · as incident-response
1. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign > Root cause
   Each pod rebuilt the catalogue index locally at start-up, so scaling out under load added pods that served partial results for their first eight minutes and made latency worse rather than better.
   affected_systems: search-api, catalogue-index · severity: major
2. PLAY-1001.md · PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   PLAY-1001 — Checkout timeouts after the payment gateway upgrade > Root cause
   The gateway upgrade shipped a connection pool whose idle timeout was 30 seconds while the load balancer held connections open for 60, so the pool handed out sockets the balancer had already closed…
   affected_systems: checkout-api, payments-gateway · severity: major
recorded to MLflow: dossier-audit/incident-audit/search
2026/10/02 07:36:31 INFO mlflow.tracing.export.async_export_queue: Flushing the async trace logging queue before program exit. This may take a while...

$ $D search incidents "Which incident lost the most money?" --as incident-response --where severity=major --limit 2
incidents · 2 documents · as incident-response
1. PLAY-1004.md · PLAY-1004 — Search latency spike during the spring campaign
   PLAY-1004 — Search latency spike during the spring campaign > Impact
   Search was degraded for 45 minutes at the campaign's peak. The campaign team recorded a loss of CHF 9'900 in attributed revenue.
   affected_systems: search-api, catalogue-index · severity: major
2. PLAY-1001.md · PLAY-1001 — Checkout timeouts after the payment gateway upgrade
   PLAY-1001 — Checkout timeouts after the payment gateway upgrade > Impact
   Finance reconciled 214 abandoned baskets against the gateway's own records, a recorded loss of CHF 18'400.
   affected_systems: checkout-api, payments-gateway · severity: major
recorded to MLflow: dossier-audit/incident-audit/search
2026/10/02 07:36:41 INFO mlflow.tracing.export.async_export_queue: Flushing the async trace logging queue before program exit. This may take a while...

$ $P read_search_trace.py
runs    0
traces  2 (the newest two)
trace   search incidents OK
  in    {"query": "Which incident lost the most money?", "where": {"severity": ["major"]}, "readers": ["incident-response"]}
  out   ["incidents-manual:PLAY-1004.md", "incidents-manual:PLAY-1001.md"]
  span  EMBEDDING ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
       text   "Instruct: Given a question about incidents, retrieve the passages of incident records and documents that answer it\nQuery:Which incident lost the most money?"
       cached False
       tokens 31
  span  RETRIEVER search incidents
       {'rank': 1, 'document_id': 'incidents-manual:PLAY-1004.md', 'chunk_id': 'f8eb080ac8af081ad1cfbe29edf7820da22f2fb0efc1cb610f0622b6f38924a5', 'score': 0.01639344262295082, 'meaning_rank': 1, 'words_rank': None}
       {'rank': 2, 'document_id': 'incidents-manual:PLAY-1001.md', 'chunk_id': '21ecfcc95dbe97fba0a768ceea1f83c2cbc19c519911bcbc535b0f36195088a5', 'score': 0.016129032258064516, 'meaning_rank': 2, 'words_rank': None}
trace   search incidents OK
  in    {"query": "Why did adding servers make it slower?", "where": {}, "readers": ["incident-response"]}
  out   ["incidents-manual:PLAY-1004.md", "incidents-manual:PLAY-1001.md"]
  span  EMBEDDING ollama:qwen3-embedding:4b-fp16@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc
       text   "Instruct: Given a question about incidents, retrieve the passages of incident records and documents that answer it\nQuery:Why did adding servers make it slower?"
       cached True
       tokens 0
  span  RETRIEVER search incidents
       {'rank': 1, 'document_id': 'incidents-manual:PLAY-1004.md', 'chunk_id': '7fe34c77f73ee761afd54d6fec05aa576c81e0c1550800731f492a809f4ee2f0', 'score': 0.01639344262295082, 'meaning_rank': 1, 'words_rank': None}
       {'rank': 2, 'document_id': 'incidents-manual:PLAY-1001.md', 'chunk_id': '891dd26d1b857a9e4b85b2294bf4c677975d9f9a6a74485fe16a6bdabdc383c2', 'score': 0.015384615384615385, 'meaning_rank': 5, 'words_rank': None}
```

The `INFO` line is MLflow's own, on stderr: it sends a trace after the trace
ends, on a thread of its own, and waits for it before the process exits.

**No run.** A run in `dossier` records something that changed: a sync, a run, an
evaluation, an index written. An `embed` that changed nothing records nothing
(R11.33 row 4). A search changes nothing, as `--plan` does not, so it opens no
run. What there is to keep is what it asked and what it answered, and that is
a trace, with the query's vector as an `EMBEDDING` span and the list as a
`RETRIEVER` span: the shape MLflow's retrieval views read (R11.35).

**Ids, not text.** In the index, and in the snapshot store, where the readers
on each row say who may read it. Copied into a trace, every passage a search
returned would be readable by whoever reads the experiment, under MLflow's
rules rather than the index's. An id finds the text again for whoever is
allowed it.

**The most money.** Compare. Nearness finds the passages about losing money,
and both impacts are that. Which loss is larger is a comparison of two
numbers, and a vector holds no number to compare. The run already extracted
each note's `loss_amount` as an amount, grounded in its note, under
`runs/<id>/extract/`. A question about the most is a question for the run's
records, not for a search.

## Cleaning up

```console
$ Q "delete from dossier_index.chunks where index = 'incidents'"
DELETE 21
$ Q "delete from dossier_index.documents where index = 'incidents'"
DELETE 4
```
