# 16 · Solution

Every command below was run against this repository, in order and in one pass,
on 2026-09-27, against the stub. The output shown is the output it produced. The
workspace's absolute path is cut from the `run` lines, and the run ids are that
pass's. Yours will differ.

## Run the prepared answer

Terminal 1:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/16-several-files-as-one-document/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 2:

```bash
E=playground/16-several-files-as-one-document
mkdir -p playground/work/16/inbox/contracts playground/work/16/gold/contracts
cp -r $E/solution/workspace/. playground/work/16/
cp -r $E/resources/documents/. playground/work/16/inbox/contracts/
cp $E/resources/verified-answers/*.json playground/work/16/gold/contracts/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/16/.env

cd playground/work/16
D=../../../.venv/bin/dossier
$D sync contract-renewal && $D run contract-renewal
$D eval contract-renewal --gold gold/contracts
```

To see the calls a run made, one line per call:

```bash
python -c "import json; [print(json.loads(l)['documents']) for l in open('/tmp/dossier-calls.jsonl')]"
```

---

## Task 1 — a folder of contracts

```yaml
sources:
  - id: contracts
    type: folder
    path: inbox/contracts/
```

```console
$ dossier sync contract-renewal
contracts  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned
```

**Where the prefix came from.** A folder source keys a file by its path under the
folder, so the subfolder is part of the key: `PLAY-ACME-2024/master.md`. Nobody wrote
`PLAY-ACME-2024` down because nobody had to. Every connector already keys a file under
what it belongs to. A Jira attachment is `INC-4821/report.pdf` (R1.6), and a
Confluence page's file is `81920114/escalation-matrix.png` (R1.18). That is why
`per_group` needs no configuration: the group is already in the key (R3.15).

## Task 2 — ask each file alone

```yaml
steps:
  - id: extract
    prompt: prompts/01_extract.md
    input: documents
    mode: per_file
    output: schemas/contract.yaml
```

```yaml
fields:
  renewal_date:  {kind: date}
  liability_cap: {kind: amount, currency: EUR}
```

The prompt is in `solution/workspace/pipelines/contract-renewal/prompts/`. It
says that a contract may be several files, each wrapped in a tag naming its key,
and that a later amendment overrides the clause it amends.

```console
$ dossier run contract-renewal
run 20260927T144614Z-ffcf · runs/20260927T144614Z-ffcf/manifest.json
  extract: 4 document(s) · 0 from cache · 0 failed · tokens not reported
```

The log, one line per call:

```
['PLAY-ACME-2024/amendment-1.md']
['PLAY-ACME-2024/amendment-3.md']
['PLAY-ACME-2024/master.md']
['PLAY-GLOBEX-2023/master.md']
```

And `extract/PLAY-ACME-2024/master.md.json`, value and span:

```
renewal_date   2026-03-31  | The agreement runs until 2026-03-31
liability_cap  2000000.0   | capped at EUR 2,000,000
```

**Which one file answers "when does ACME's contract end"?** None of them. The
master answers with the date amendment 3 replaced, and amendment 3 does not say
what the liability cap is. The prompt's sentence about a later amendment is
useless to a call that is shown one file. The line that matters is the prompt
saying *"a contract may be several files"* while `per_file` shows it one.

## Task 3 — ask each contract

`mode: per_group`, and nothing else changed:

```console
$ dossier run contract-renewal
run 20260927T144617Z-0022 · runs/20260927T144617Z-0022/manifest.json
  extract: 2 group(s) · 0 from cache · 0 failed · tokens not reported
```

```
['PLAY-ACME-2024/amendment-1.md', 'PLAY-ACME-2024/amendment-3.md', 'PLAY-ACME-2024/master.md']
['PLAY-GLOBEX-2023/master.md']
```

```console
$ ls runs/20260927T144617Z-0022/extract/
PLAY-ACME-2024.json
PLAY-ACME-2024.meta.json
PLAY-GLOBEX-2023.json
PLAY-GLOBEX-2023.meta.json
```

`PLAY-ACME-2024.json`, shortened:

```json
{
  "document": "PLAY-ACME-2024",
  "fields": [
    {"field": "renewal_date", "value": "2027-03-31",
     "source": {"document": "PLAY-ACME-2024/amendment-3.md",
                "span": "the agreement now runs until 2027-03-31"}},
    {"field": "liability_cap", "value": 2000000.0, "currency": "EUR",
     "source": {"document": "PLAY-ACME-2024/master.md",
                "span": "capped at EUR 2,000,000"}}
  ]
}
```

One answer, two citations, each naming the member its span is in (R6.22). A
group has no text of its own, so a citation of `PLAY-ACME-2024` itself would be
invalid: there is nothing to look for the span in.

**Why GLOBEX is a call of its own.** A key with no second member is a group of one,
named by its first segment. The call holds exactly what task 2's call for
`PLAY-GLOBEX-2023/master.md` held, one document wrapped under its own key, with the
same prompt (R3.13). A flat folder is a folder of groups of one, and on it
`per_group` asks what `per_file` asks.

**Why it was not served from cache anyway.** Look at the `inputs` of
`PLAY-GLOBEX-2023.meta.json`:

```json
"inputs": [
  {"path": "documents/PLAY-GLOBEX-2023", "role": "documents", "hash": "ad59a0db…"},
  {"path": "group/PLAY-GLOBEX-2023",     "role": "group",     "hash": "355dcacf…"}
]
```

The `group` input is the group's name, and it is in the key. Without it the two
calls had the same key, so task 3 was served task 2's answer. That answer said
`"document": "PLAY-GLOBEX-2023/master.md"` and was filed as `PLAY-GLOBEX-2023.json`. A
cached answer is served byte for byte (R5.5), so nothing corrects its
`document` on the way out. What differs has to be in the key. A live run of this
exercise found exactly that, with the suite green. R5.14 row 5 is the rule that
came of it, and it follows R5.10 row 5, the same mistake one level down.

**`PLAY-ACME-2024/amendments/amendment-5.md`** joins `PLAY-ACME-2024`. The group is the
first segment, not the last directory (R3.15 row 5). Otherwise a contract that
files its amendments in a subfolder would be two contracts.

## Task 4 — verified per contract

```json
{
  "document": "PLAY-ACME-2024",
  "verified_by": "a.aleks",
  "verified_at": "2026-09-27",
  "fields": {
    "renewal_date":  {"value": "2027-03-31"},
    "liability_cap": {"value": 2000000.00, "currency": "EUR"}
  }
}
```

```console
$ dossier eval contract-renewal --gold gold/contracts
2 groups · 2 fields · overall 100.0%
  renewal_date       100.0%
  liability_cap      100.0%
```

`2 groups`, not `4 documents`: the first line counts what was scored, and the
run answered for two contracts (R7.32).

**A gold file whose `document` is `PLAY-ACME-2024/master.md`** scores nothing. The run
answered for `PLAY-ACME-2024`, no answer is filed under a member, and gold is matched
by its `document` field, not by its filename (R7.32 row 3). The eval then reads
`1 group`.

**What makes `renewal_date` right** is that its value matches the verified one,
`2027-03-31`. Which member it was cited from is grounding's question, and
grounding already answered it: the span is in amendment 3 (R6.4, R6.22). A value
grounded in the master that said `2027-03-31` would score the same. It would also
be a strange thing for a master to say.

## Task 5 — an amendment is filed

```console
$ cp resources/later/amendment-4.md inbox/contracts/PLAY-ACME-2024/
$ dossier sync contract-renewal
contracts  4 known · 0 changed · 1 new -> 5 fetched
ledger updated · 1 new snapshots · 0 tombstoned

$ dossier run contract-renewal
warning: the source has moved since run 20260927T144617Z-0022: PLAY-ACME-2024/amendment-4.md new
run 20260927T144622Z-4243 · runs/20260927T144622Z-4243/manifest.json
  extract: 2 group(s) · 1 from cache · 0 failed · tokens not reported
```

```
['PLAY-ACME-2024/amendment-1.md', 'PLAY-ACME-2024/amendment-3.md', 'PLAY-ACME-2024/amendment-4.md', 'PLAY-ACME-2024/master.md']
```

One call, not two. ACME's key holds every member's inputs, so a new member is a
new key. GLOBEX's holds its own members and no others, so a document filed in
another contract cannot move it (R5.14). That is R5.10 one level up: adding a
document re-runs the stages for that document only, and here "that document" is
the contract it joined.

`5 fetched` because a folder has no version marker to compare, so every file
is read again, as in exercise 01. `1 new snapshots` because only one of them was
new bytes. The four already held were not written again (R2.14).

## Task 6 — replay the contract as it was

```console
$ dossier run --replay runs/20260927T144617Z-0022
replayed 20260927T144617Z-0022 · contract-renewal
  extract: 2 artifact(s) from cache
2 artifact(s) reproduced · no model calls · written to runs/20260927T144617Z-0022/replays/20260927T144624Z-3133/
```

**Where the three came from.** The manifest. It pins every document the run read
by key and snapshot (R4.4), and a group is computed from keys alone, so the
replay recomposes the groups the run asked about without their being recorded
anywhere else (R4.15). Amendment 4 is held now, but the run never pinned it, so
the replay never sees it, just as it would not see a prompt edited since (R4.7).

**Had it grouped what is held today,** it would have looked for the four-member
key. A cache entry does exist under that key, written by task 5's run, but it
answers a different question than the one run `…0022` asked. A replay that
quietly served it would be reproducing the wrong run. With no task 5 behind it,
the replay would find no entry at all and stop.

## Task 7 — the step that cannot read a group

```yaml
  - id: verify
    prompt: prompts/01_extract.md
    input: [documents, extract]
    mode: per_file
    output: schemas/contract.yaml
```

```console
$ dossier run contract-renewal --plan
pipeline.yaml: step 'verify' is mode: per_file and reads 'extract', which is mode: per_group and answers once per group. Only a per_group or aggregate step can read it (R3.16).
exit 2
```

**Which answer a call about `PLAY-ACME-2024/master.md` would have been handed.**
Either `extract/PLAY-ACME-2024.json`, which is about four files, not the one the call
is asking about, or nothing, which drops the evidence the step was declared to
read. Neither is right, so the pipeline is refused when it loads, before a
snapshot is read (R3.16). That is the same moment a `per_part` step over text is
refused (R3.12 row 5).

**As `per_group`,** it is accepted. The prompt has to inject `{{extract}}` as
well, or the plan is refused for a declared input nothing uses. Each `verify`
call then holds its group's members and the group's own answer. Its record's
inputs, from a run made at the end of this pass:

```
documents/PLAY-ACME-2024
extract/PLAY-ACME-2024
group/PLAY-ACME-2024
```

```console
  verify: 2 group(s) · 0 from cache · 0 failed · tokens not reported
```

The reverse is sound, and not refused. A `per_group` step reading a `per_file`
step gets each member's answer under the member's key, as it gets each member's
text (R3.16 row 4).

## Task 8 — a quote from the wrong contract

Terminal 1:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/16-several-files-as-one-document/resources/replies-wrong-contract.json \
  --replies playground/16-several-files-as-one-document/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

```console
$ rm -rf .dossier/cache/stage/
$ dossier run contract-renewal
run 20260927T144631Z-f2ec · runs/20260927T144631Z-f2ec/manifest.json
  extract: 2 group(s) · 0 from cache · 0 failed · 1 finding(s) · tokens not reported
    PLAY-ACME-2024  renewal_date: cites 'PLAY-GLOBEX-2023/master.md', which was not an input to this stage. Inputs were ['PLAY-ACME-2024/amendment-1.md', 'PLAY-ACME-2024/amendment-3.md', 'PLAY-ACME-2024/amendment-4.md', 'PLAY-ACME-2024/master.md'] (R6.3).
```

**Why that is worse than a citation that leads nowhere.** A citation that leads
nowhere fails the first time anyone follows it. This one succeeds. The sentence
is really in GLOBEX's contract, so a reviewer who opens the cited file finds the
quote, word for word, and signs off. Nothing about the citation says the call
that produced it was never shown that file. The date is GLOBEX's date, and ACME's
renewal would be missed by three months. A group's citable documents are its
members and nobody else's (R6.22), and R6.3 is the rule that says why.

The stub's first rule matches only a call that holds amendment 4, so it fires
only after task 5. Before that, the ACME call falls through to `replies.json`.

---

## Where this leaves the contract audit

`docs/second-use-case.md` is a paper review of this same contract audit, written
before any of it could run. Its finding 1, "there is no way to say these files
are one document", is the gap this exercise shows closed.
