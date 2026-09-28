# 19 · Solution

Every command below was run against this repository, in order and in one pass,
on 2026-09-28, against the stub. The output shown is the output it produced. The
workspace's absolute path is cut from the `run` lines, and the run ids are that
pass's. Yours will differ.

## Run the prepared answer

Terminal 1:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/19-answers-that-are-not-text/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Terminal 2:

```bash
E=playground/19-answers-that-are-not-text
mkdir -p playground/work/19/inbox/contracts playground/work/19/gold/contracts
cp -r $E/solution/workspace/. playground/work/19/
cp $E/resources/documents/*.md playground/work/19/inbox/contracts/
cp $E/resources/verified-answers/*.json playground/work/19/gold/contracts/
cp playground/02-a-pipeline-end-to-end-on-markdown/resources/env.sample playground/work/19/.env

cd playground/work/19
D=../../../.venv/bin/dossier
$D sync contract-terms && $D run contract-terms
$D eval contract-terms --gold gold/contracts
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
$ dossier sync contract-terms
contracts  0 known · 0 changed · 3 new -> 3 fetched
ledger updated · 3 new snapshots · 0 tombstoned
```

## Task 2 — three kinds, and a prompt that says how to answer them

```yaml
fields:
  auto_renew:    {kind: boolean}
  notice_period: {kind: duration}
  sites:         {kind: list}
```

The prompt is in `solution/workspace/pipelines/contract-terms/prompts/`. It
takes the three fields one at a time. `auto_renew` is `true` or `false`, and
`null` with a reason when the contract says neither: "saying nothing is not
saying no". `notice_period` is a whole number and a unit, as the contract states
it, never converted. `sites` is one record per site, each citing its own
sentence, and every other field is answered once.

```console
$ dossier run contract-terms
run 20260928T185420Z-9bc3 · runs/20260928T185420Z-9bc3/manifest.json
  extract: 3 document(s) · 0 from cache · 0 failed · tokens not reported
```

`runs/20260928T185420Z-9bc3/extract/PLAY-ACME-2024.md.json`, one line per record:

```
auto_renew     True     | renews automatically for successive one-year terms
notice_period  90 days  | ninety (90) days' written notice
sites          Zurich   | sites in Zurich
sites          Basel    | Zurich, Basel and Geneva
```

**What one string could not do.** Exercise 05's `"reporting-export"` had one
source, one span behind the whole answer. A list answered as one string,
`"Zurich, Basel, Geneva"`, would have one span too. A site the contract never
names could ride along on the evidence for two it does, and the span check would
pass. Answered one record per site, each item is grounded on its own sentence
(spec 006, "A list is answered one record per item"), and one ungrounded item
fails the list (R7.42).

**Why nothing new was needed.** A record still holds one value, and the schema
the model is shown still limits `field` to the declared names and says nothing
of kinds. So a declaration with a `list` in it generates the same schema as one
without (R6.12), and the only new thing is permission: a `list` may be answered
more than once. Had the list been an array inside one record, the record's shape
would have changed. The generated schema changes with it, and so does every
stage key any pipeline ever wrote.

## Task 3 — verified answers, and a score per kind

```console
$ dossier eval contract-terms --gold gold/contracts
3 documents · 3 fields · overall 77.8%
  auto_renew         100.0%
  notice_period       66.7%   <- weakest
    PLAY-GLOBEX-2023.md '90 days' does not match '3 months': a month is not a fixed number of days, so the two are not compared as lengths
  sites               66.7%   items: precision 100.0% (4/4), recall 80.0% (4/5)   <- weakest
    PLAY-ACME-2024.md missing: Geneva
```

**INITECH's `auto_renew`.** The run abstained: `null`, "the agreement says
nothing about renewal", and gold abstains too, so it is correct (R7.3). `false`
would have been an answer, the claim that the contract does not renew, and
against a gold `null` a run that answers where the document is silent is
scored as supplying a value (R7.36 row 7). "Does not renew" and "does not say"
send someone to different clauses.

**Three months against ninety days.** Three months' notice given on 1 December
runs to 1 March: 90 days, or 91 in a leap year. Given on 1 May, it is 92. A
month is 28 to 31 days, so no fixed number of days is three months. The two
agree only by convention, and a contract written in months means months. The
scorer converts only where the conversion is exact, seven days to a week and
twelve months to a year, and says why when it does not (R7.38).

**Reading the list line.** One verdict per contract (R7.41): ACME's list is
wrong, the other two are right, so 2 of 3. The items say which way it is wrong.
Precision is 4 of 4: every site the run named is in gold, so it invented
nothing. Recall is 4 of 5: gold's five sites include one the run did not name,
so it missed one. A run that named `Lausanne` for GLOBEX would make GLOBEX
incorrect too, `sites` 33.3%. Precision would fall to 4 of 5, 80.0%, and recall
would stay at 4 of 5: an invented site costs precision, and a missed one costs
recall (R7.43). Neither figure gates anything. `--compare` decides a regression on
the percentage alone.

## Task 4 — gold a run could never match

```console
$ dossier eval contract-terms --gold gold/contracts
contract-terms: PLAY-ACME-2024.md: sites is a list, and gold writes a list as an array, such as ["a", "b"]; found 'Zurich, Basel, Geneva'
contract-terms: PLAY-GLOBEX-2023.md: sites is an empty list; write null, with a reason, for a document that names none
contract-terms: PLAY-INITECH-2025.md: notice_period is duration, and only a list field holds an array
$ echo $?
2
```

**Not split.** `"Basel, Dreispitz"` is one site, and split on its comma it is
two. Splitting would guess what the reviewer meant, and a wrong guess would score
the run against a gold answer nobody wrote. It is also the shape a gold set
written while the field was a `reference` has, so the refusal is the one a
change of kind runs into first.

**`[]` against `null`.** A run answering one record per item has one way to say
"no site": one record, `null`, with a reason. "The contract names none" and "the
contract does not say" are both that record, told apart only in a reason nobody
scores. A gold set able to hold the difference would score it against answers
that cannot. So gold writes `null` with a reason, as the run does (R7.44).

All three are refused before anything is scored. An answer in the wrong shape is
the gold set's mistake, and scoring the run against it would blame the run.

## Task 5 — a kind that is not there

```console
$ dossier run contract-terms --plan
pipeline.yaml: step 'extract': contract.yaml: field 'notice_days' declares kind 'number', which is not one of: amount, date, reference, enum, boolean, duration, list, free_text
$ echo $?
2
```

A `number` would compare exactly as `amount` does, and a second name for one
scorer is one more thing to read (R7.39 row 3). And `notice_days` is the wrong
field for GLOBEX whatever its kind: its contract gives notice in months, and a
number of days is a conversion nobody can make exactly (task 3).

## Task 6 — words that are not a boolean or a duration

```console
$ dossier run contract-terms
run 20260928T185507Z-6c4a · runs/20260928T185507Z-6c4a/manifest.json
  extract: 3 document(s) · 0 from cache · 0 failed · tokens not reported
$ dossier eval contract-terms --gold gold/contracts
3 documents · 3 fields · overall 66.7%
  auto_renew          66.7%
    PLAY-ACME-2024.md 'yes' is not a well-formed boolean, so it cannot be compared with True
  notice_period       66.7%
    PLAY-ACME-2024.md '13 weeks' does not match '90 days'
  sites               66.7%   items: precision 100.0% (4/4), recall 80.0% (4/5)
    PLAY-ACME-2024.md missing: Geneva
```

**Unreadable is not wrong.** `"yes"` may well mean `true`, but the fix for it is
in the prompt, which should ask for `true` or `false`. A disagreement would send
someone to the contract to look for a discrepancy that is not there. Reading
`yes` would start a vocabulary, `y`, `on`, `ja`, `oui`, that nobody agreed to and
every scorer after it would inherit (R7.36).

**Weeks compare, months do not.** A week is exactly seven days, so `13 weeks` is
91 days and is compared with 90, and is one day short (R7.38 row 3). A month is
not a fixed number of days, so `3 months` is not compared with `90 days` at all,
and the detail says why (row 4). `12 weeks` against a gold `84 days` would be
correct.

**No weakest.** When every field scores the same, none is marked. A marker on
every line, or on one chosen arbitrarily, says nothing about where the work is
(R7.2).

## Task 7 — one question, two answers

```console
$ dossier run contract-terms
run 20260928T185524Z-3fef · runs/20260928T185524Z-3fef/manifest.json
  extract: 3 document(s) · 0 from cache · 0 failed · tokens not reported
$ dossier eval contract-terms --gold gold/contracts
3 documents · 3 fields · overall 88.9%
  auto_renew         100.0%
  notice_period      100.0%
  sites               66.7%   items: precision 100.0% (4/4), recall 80.0% (4/5)   <- weakest
    PLAY-ACME-2024.md missing: Geneva
$ python -c "import json; [print(json.loads(l)['documents']) for l in open('/tmp/dossier-calls.jsonl')]"
['PLAY-ACME-2024.md']
['PLAY-GLOBEX-2023.md']
['PLAY-GLOBEX-2023.md']
['PLAY-INITECH-2025.md']
```

**The error.** GLOBEX's first answer was well-formed JSON and named no unknown
field, but it gave `notice_period` two records. That is two answers to one
question, and nothing after it could say which the model meant. The run refused
it as a validation failure, and the one retry carried the refusal inside
`<validation_error>`:

```
notice_period: answered more than once. Only a field declared `list` is answered once per item; answer every other field once
```

The retry answered once, `3 months`, and that is the answer that was kept
(R6.24, R6.2).

**Where the difference comes from.** The declaration. The model is not told a
kind, but the run is: `load_output_schema` reads which fields are `list`, and
the check on the reply lets those, and only those, repeat. So the prompt has to
ask for one record per site. Nothing enforces that a model does. But when a model
repeats any other field, the run notices.

**A third attempt.** There is none. A second refusal fails GLOBEX alone: no
answer written, nothing cached, and the other two contracts complete (R6.9). A
model that cannot give the shape twice will not on the fifth try either, and a
retry loop with no bound turns a bad prompt into a bill (R6.2).
