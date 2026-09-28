# 19 · Answers that are not text

**You will build:** a contract audit asking three questions whose answers are
not a piece of text: does the contract renew on its own, how much notice does
it take to leave, and which sites does it cover. Then you will score them.

**You will learn:** how a field's `kind` picks its scorer; why `false` is an
answer and `null` is not; why three months' notice is not ninety days'; how a
list is answered one record per item and scored as a set; what item precision
and recall say that a percentage does not; which gold answers are refused
before anything is scored; and what happens when a model answers one question
twice.

**Uses the stub model.** Offline, seconds, zero cost.

---

## Background, in one paragraph

Every field so far held an amount, a date, a word from a list, or prose. A
contract audit asks other things. `auto_renew` is yes or no.
`notice_period` is a length of time. `sites` is several places.
Scored as strings, each goes wrong in its own way. `"false"` and `false` would
differ. `"3 months"` and `"90 days"` would differ for the wrong reason. `"Zurich,
Basel"` and `"Basel, Zurich"` would differ for no reason at all. So each of those
three has a kind of its own (spec 007, "Scorers"). A kind is written once, in the
field declaration, and it is never shown to the model, so declaring one moves no
cache key (R6.12). That is also why the prompt has to say how each field is
answered.

---

## The documents

```
resources/documents/
  PLAY-ACME-2024.md      renews every year, 90 days' notice, three delivery sites
  PLAY-GLOBEX-2023.md    says it does not renew, three months' notice, one site
  PLAY-INITECH-2025.md   says nothing about renewal or notice, one site
```

Terminal 1, the stub:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/19-answers-that-are-not-text/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

## Task 1 — a folder of contracts

Make a workspace under `playground/work/19/`. Copy `resources/documents/` to
`inbox/contracts/`, and copy the `.env` from exercise 02's
`resources/env.sample`. Write `sources.yaml` with one `folder` source,
`contracts`, over `inbox/contracts/`, and sync.

**Checkpoint.** `contracts  0 known · 0 changed · 3 new -> 3 fetched`.

## Task 2 — three kinds, and a prompt that says how to answer them

Write `pipelines/contract-terms/`: one `per_file` step, `extract`, reading
`documents`, over a declaration of three fields:

```yaml
fields:
  auto_renew:    {kind: boolean}
  notice_period: {kind: duration}
  sites:         {kind: list}
```

Then write the prompt. The model is never told a field's kind, so the prompt
says, field by field, what an answer looks like:

- `true` or `false` for `auto_renew`, and `null` with a reason when the
  contract says neither;
- a whole number and a unit for `notice_period`, as the contract states it;
- **one record per site** for `sites`, each citing its own sentence.

Run it.

**Checkpoint.** `extract: 3 document(s) · 0 from cache · 0 failed`. Open ACME's
answer under `runs/<id>/extract/`:

```
auto_renew     True     | renews automatically for successive one-year terms
notice_period  90 days  | ninety (90) days' written notice
sites          Zurich   | sites in Zurich
sites          Basel    | Zurich, Basel and Geneva
```

`sites` is answered twice, once per site, and every other field once.

- In exercise 05, `affected_systems` was one string, `"reporting-export"`. What
  could a single string not do for a list of three sites? Look at where each of
  the two `sites` records points (spec 006, "A list is answered one record per
  item").
- Why does a list not need a new record shape, or a new schema for the model?
  What would have moved if it had? (R6.12.)

## Task 3 — verified answers, and a score per kind

Copy `resources/verified-answers/` to `gold/contracts/` and read the three
files. ACME's `sites` is an array. INITECH's `auto_renew` is `null`, with a
reason. Eval.

**Checkpoint.**

```
3 documents · 3 fields · overall 77.8%
  auto_renew         100.0%
  notice_period       66.7%   <- weakest
    PLAY-GLOBEX-2023.md '90 days' does not match '3 months': a month is not a fixed number of days, so the two are not compared as lengths
  sites               66.7%   items: precision 100.0% (4/4), recall 80.0% (4/5)   <- weakest
    PLAY-ACME-2024.md missing: Geneva
```

- INITECH's `auto_renew` is scored correct. What did the run answer, and why
  would `false` have been wrong? (R7.3, R7.36 row 7.)
- The run says GLOBEX gives 90 days' notice, and the contract says three months.
  In a year when the notice starts on 1 December, how many days is that? And
  why is the answer "it depends" enough to score the two as different? (R7.38.)
- `sites` scored one verdict per contract, not one per site (R7.41). Which
  figure on its line tells you the run missed a site rather than inventing one?
  What would a run that named `Lausanne` for GLOBEX do to each figure? (R7.43.)

## Task 4 — gold a run could never match

Edit the gold set three ways at once. In ACME's file, write `sites` as the
string `"Zurich, Basel, Geneva"`. In GLOBEX's, write `sites` as `[]`. In
INITECH's, write `notice_period` as `["1 month"]`. Eval.

**Checkpoint.** Exit 2, one line per mistake, and no score printed:

```
contract-terms: PLAY-ACME-2024.md: sites is a list, and gold writes a list as an array, such as ["a", "b"]; found 'Zurich, Basel, Geneva'
contract-terms: PLAY-GLOBEX-2023.md: sites is an empty list; write null, with a reason, for a document that names none
contract-terms: PLAY-INITECH-2025.md: notice_period is duration, and only a list field holds an array
```

- Why is the comma string refused rather than split? Think of a site called
  `Basel, Dreispitz`.
- Why is `[]` refused when `null` is not? How would a run, answering one record
  per item, say "this contract names no site"? (R7.44.)

Put the gold set back before task 5.

## Task 5 — a kind that is not there

Add `notice_days: {kind: number}` to the declaration and plan the run
(`run --plan`).

**Checkpoint.** Refused before anything runs, naming every kind there is:

```
pipeline.yaml: step 'extract': contract.yaml: field 'notice_days' declares kind 'number', which is not one of: amount, date, reference, enum, boolean, duration, list, free_text
```

A count of days is an `amount` with no `currency`, so why is there no `number`?
And why would `notice_days: {kind: amount}` be the wrong field for GLOBEX
anyway? Put the declaration back.

## Task 6 — words that are not a boolean or a duration

Restart the stub with `resources/replies-words.json`. In it, ACME's
`auto_renew` is `"yes"`, and its `notice_period` is `"13 weeks"`. Delete
`.dossier/cache/stage/`, run, and eval.

**Checkpoint.**

```
3 documents · 3 fields · overall 66.7%
  auto_renew          66.7%
    PLAY-ACME-2024.md 'yes' is not a well-formed boolean, so it cannot be compared with True
  notice_period       66.7%
    PLAY-ACME-2024.md '13 weeks' does not match '90 days'
  sites               66.7%   items: precision 100.0% (4/4), recall 80.0% (4/5)
    PLAY-ACME-2024.md missing: Geneva
```

- `"yes"` is reported as unreadable, not as a disagreement. Why do the two need
  different work? What vocabulary would reading `yes` start? (R7.36.)
- `13 weeks` is compared with `90 days`, and `3 months` was not. What is the
  difference? (R7.38 rows 3 and 4.)
- Every field is at 66.7%, and no line says `<- weakest`. Why not? (R7.2.)

## Task 7 — one question, two answers

Restart the stub with `resources/replies-twice.json`. GLOBEX's first answer
gives `notice_period` twice, `"3 months"` and `"90 days"`, each citing the same
sentence. Delete `.dossier/cache/stage/`, run, and eval, then count the calls in
the log.

**Checkpoint.** `extract: 3 document(s) · 0 from cache · 0 failed`,
`notice_period 100.0%`, and **four** calls in the log, two of them for GLOBEX.

- The second GLOBEX call matched a rule that needs `<validation_error>` in the
  prompt. What did that error say, and which rule put it there? (R6.24, R6.2.)
- `sites` may be answered twice and `notice_period` may not. Where does that
  difference come from, given that the model is never shown a kind?
- What would a third GLOBEX answer with two notice periods have done? Why is the
  budget one retry, and not three? (R6.2, R6.9.)

---

## Done when

- you can say, for each kind, what counts as the same answer and what is
  refused as unreadable;
- you can explain why `null` and `false` are different answers, and why `90
  days` and `3 months` are different notice;
- you can read a list's line: its percentage, its precision and its recall, and
  what each would do if the run missed an item or invented one;
- you know which gold answers are refused before scoring, and why a list is
  written as an array.

To see what a real model makes of the prompt, point `.env` at your own endpoint
(the playground index, "Using a real model instead"). Then check whether it
answers `sites` one record per site. The run cannot check that the prompt
asks for it, and R6.24 is what catches a model that answers any other field
twice.

**Back to:** [the playground index](../README.md).
