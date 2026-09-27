# 16 · Several files as one document

**You will build:** a contract audit in which a contract is a folder of files —
a master agreement and its amendments — asked about once as a whole, and scored
against one verified answer per contract.

**You will learn:** what a group is and where it comes from, why no configuration
names it, what a `per_group` step does to calls, keys, citations, scoring and
replays, and why the one step that cannot read a group's answer is refused
before anything runs.

**Uses the stub model.** Offline, seconds, zero cost.

---

## Background, in one paragraph

Everything up to now had one file answer one question. A supplier contract does
not work that way. The master agreement sets the liability cap and a term, and
amendment 3 extends the term. Ask the master alone when the contract ends, and it
honestly answers with the date amendment 3 replaced. `per_file` asks each file
alone, and `aggregate` asks one question of every contract at once, which is one
enormous call nobody can cache or score per contract
(`docs/second-use-case.md`, finding 1). `per_group` is the fourth mode. A
document's group is its key up to the first `/`, and a folder source keys a file
by its path under the folder. So a contract kept in its own subfolder already is
a group, and the step asks one question per contract (R3.15).

---

## The documents

```
resources/documents/
  ACME-2024/
    master.md          the liability cap, and a term ending 2026-03-31
    amendment-1.md     a new invoicing address; answers nothing audited
    amendment-3.md     the term extended to 2027-03-31
  GLOBEX-2023/
    master.md          a contract with no amendments
resources/later/
  amendment-4.md       an ACME amendment filed after the first run (task 5)
```

Terminal 1, the stub:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/16-several-files-as-one-document/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Its log records, for every call, the documents the prompt held, by the key each
was wrapped under (R3.13). That line is how you will tell the modes apart.

## Task 1 — a folder of contracts

Make a workspace under `playground/work/16/`. Copy `resources/documents/` to
`inbox/contracts/`, keeping the subfolders, and copy the `.env` from exercise
02's `resources/env.sample`. Write `sources.yaml` with one `folder` source,
`contracts`, over `inbox/contracts/`. Then sync.

**Checkpoint.**

```
contracts  0 known · 0 changed · 4 new -> 4 fetched
```

Four documents, and every key starts with its contract: `ACME-2024/master.md`.
Where did that prefix come from? Nobody wrote it anywhere.

## Task 2 — ask each file alone

Write `pipelines/contract-renewal/` with one step, `extract`, reading
`documents`, in mode **`per_file`**, over a declaration of two fields:
`renewal_date` (`date`) and `liability_cap` (`amount`, `EUR`). Write the prompt.
It must say that a contract may be several files and that a later amendment
overrides the clause it amends. Run it.

**Checkpoint.** `extract: 4 document(s)`, four calls in the log, each holding one
document. Now open `extract/ACME-2024/master.md.json`:

```
renewal_date  2026-03-31  | The agreement runs until 2026-03-31
```

The model did nothing wrong: that is what the master says. The right date is in a
file that call was never shown. Which one file answers "when does ACME's
contract end"?

## Task 3 — ask each contract

Change the mode to `per_group`. Nothing else. Run again.

**Checkpoint.**

```
  extract: 2 group(s) · 0 from cache · 0 failed
```

and two new lines in the log:

```
['ACME-2024/amendment-1.md', 'ACME-2024/amendment-3.md', 'ACME-2024/master.md']
['GLOBEX-2023/master.md']
```

`extract/` now holds `ACME-2024.json` and `GLOBEX-2023.json`. Open ACME's: one
answer, `"document": "ACME-2024"`, with `renewal_date` cited from amendment 3
and `liability_cap` from the master.

- Why is GLOBEX a call of its own, and why is its call identical to the one task
  2 made for its only file?
- If the calls are identical, why was GLOBEX **not** served from cache? Look at
  the `inputs` of `GLOBEX-2023.meta.json` and find the one that is not a document.
  Then read R5.14 row 5 for what a live run of this exercise found before it
  was there.
- A folder under `ACME-2024/amendments/` would put a file two levels down. Which
  group would it join? (R3.15 row 5.)

## Task 4 — verified per contract

Copy `resources/verified-answers/` to `gold/contracts/` and read one. Its
`document` is `ACME-2024`, the contract, not a file. Eval.

**Checkpoint.**

```
2 groups · 2 fields · overall 100.0%
```

Then say what a gold file whose `document` is `ACME-2024/master.md` would score,
and why (R7.32 row 3). Which member a value was cited from is grounding's
question, not scoring's: what makes `renewal_date` right?

## Task 5 — an amendment is filed

Copy `resources/later/amendment-4.md` into `inbox/contracts/ACME-2024/`, sync,
and run.

**Checkpoint.** `2 group(s) · 1 from cache`, and one new line in the log, holding
four ACME files. GLOBEX was not asked. Find the rule that promises it, and the one
it is modelled on (R5.14, R5.10).

## Task 6 — replay the contract as it was

Replay the run from task 3:

```bash
dossier run --replay runs/<task 3's run id>
```

**Checkpoint.** `2 artifact(s) reproduced · no model calls`. The workspace holds
four ACME files now, and the replay still reproduced the three-file answer. Where
did it get the three from? (R4.15.) What would it have looked for if it had
grouped what is held today?

## Task 7 — the step that cannot read a group

Append a second step, `verify`, in mode `per_file`, reading
`[documents, extract]`. Plan the run with `--plan`.

**Checkpoint.** Refused before anything runs, with exit 2:

```
pipeline.yaml: step 'verify' is mode: per_file and reads 'extract', which is
mode: per_group and answers once per group. Only a per_group or aggregate step
can read it (R3.16).
```

Which answer would a `per_file` call about `ACME-2024/master.md` have been
handed? Say why both possibilities are wrong. Then make `verify` `per_group`,
and say what each of its calls holds. Put the pipeline back before task 8.

## Task 8 — a quote from the wrong contract

Restart the stub with `resources/replies-wrong-contract.json` given first. In
that reply, ACME's `renewal_date` is quoted from GLOBEX's contract. Delete
`.dossier/cache/stage/` and run.

**Checkpoint.**

```
  extract: 2 group(s) · 0 from cache · 0 failed · 1 finding(s)
    ACME-2024  renewal_date: cites 'GLOBEX-2023/master.md', which was not an input to this stage. ...
```

The sentence is really in GLOBEX's contract, so a reviewer who followed the
citation would find it. Why is that worse than a citation that leads nowhere?
(R6.22, R6.3.)

---

## Done when

- a contract of several files is asked about once, and its answer cites the file
  each value came from;
- you can say where a group comes from without looking, and why that needs no
  configuration;
- you can explain, per rule, what a `per_group` step does to calls (R3.15), keys
  (R5.14), citations (R6.22), scoring (R7.32), replays (R4.15), and the steps
  after it (R3.16).

A judged field in a `per_group` step is put to the judge with every member of
its group (R7.33). Exercise 07 shows calibration. The same steps work here, with
a sample whose cases name a contract.

**Back to:** [the playground index](../README.md).
