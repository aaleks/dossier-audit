# 05 · A gold set and `dossier eval`

**You will build:** a gold set of verified answers, score a run against it, and
compare two runs field by field.

**You will learn:** what a gold file must carry and why, how each field kind is
scored, what a `null` in gold means, and how to tell a real improvement from a
better-looking headline.

**Uses the stub model.** Start it before task 2.

---

## Background, in one paragraph

The gold set is the asset the whole system is measured against, so an edit to it
is a change to the definition of correct. Every score `dossier` has ever reported
is a claim about agreement with this data. That is why each gold file carries a
reviewer and a date, why nothing but a reviewer's decision may enter it, and why
this repository's hooks stop an *agent* writing one at all: "editing gold until a
score passes is how a threshold dies" (`.claude/hooks/guard-edits.sh`, R7.7).

Which is also why the gold files for this exercise are in `resources/` as
proposals, and copying them into `gold/` is your job.

---

## Task 1 — write the gold set

Read `resources/verified-answers/*.json`. Four files, one per note, each holding:

```json
{
  "document": "PLAY-1001.md",
  "verified_by": "a.aleks",
  "verified_at": "2026-09-17",
  "fields": { "loss_amount": {"value": 18400.00, "currency": "CHF"}, … }
}
```

Check them against the notes in `playground/corpus/incidents/` — that is the
review, and it is the part that matters. Then copy them into your workspace at
`gold/incidents/`, changing `verified_by` to your own name.

Two questions to answer from the files themselves:

- `PLAY-1002.md` has `"loss_amount": {"value": null, "reason": …}`. What is the
  difference between that and leaving `loss_amount` out of the file entirely?
- The `document` key is `PLAY-1001.md`, with the extension, while the file is
  called `PLAY-1001.json`. Which of the two does `dossier` match on, and why is
  that the right choice?

## Task 2 — score a run

Sync, run, and then:

```bash
dossier eval incident-audit --gold gold/incidents
```

**Checkpoint.** An overall figure, then every declared field with its own
percentage. Note what the report never does: print the overall figure alone. A
field at 50% and one at 100% need different work, and a single blended number
hides which is which (R7.2).

Try `dossier eval` on a workspace with no run, and read the message.

## Task 3 — make one answer wrong, and find out what "wrong" means

You cannot change a run's answer by editing the stub: the answer is not in the
cache key, so the run is served from the cache. To ask the model a different
question you have to *change the question* — edit the prompt.

Append this line to `prompts/01_extract.md`:

```
When two figures are given, prefer the figure finance reconciled.
```

Restart the stub with the v2 overrides layered in front of the base replies:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/05-a-gold-set-and-dossier-eval/resources/replies-prompt-v2.json \
  --replies playground/05-a-gold-set-and-dossier-eval/resources/replies.json \
  --port 8099 --log /tmp/dossier-calls.jsonl
```

Run `--plan` first — it should tell you exactly why this run will not be cached —
then run, then eval.

**Checkpoint.** Four answers changed and only two scores moved. Before you look
at the solution, work out which is which and why:

| document | field | the run now answers |
|---|---|---|
| PLAY-1001 | loss_amount | `"CHF 18'400"` as a string, gold says `18400.00` |
| PLAY-1001 | severity | `"MAJOR"`, gold says `"major"` |
| PLAY-1001 | resolution_date | `"04.03.2026"`, gold says `"2026-03-04"` |
| PLAY-1002 | resolution_date | `"19.03.2026"`, gold says `"2026-03-19"` |
| PLAY-1002 | loss_amount | `0.0`, gold says `null` |

Two of the date rows are the interesting pair: same format, opposite verdicts.
The reason is in `_as_date` in `src/dossier/domain/scoring.py`, and it is the best
single example in this codebase of refusing to guess.

## Task 4 — compare the two runs

```bash
ls runs/
dossier eval incident-audit --gold gold/incidents --compare <run A> <run B>
```

**Checkpoint.** Per-field deltas and a `<- regression` marker. This is the change
gate: the question "did this prompt edit help?" has one honest answer, and it is
field by field.

Then break it deliberately: add a fifth note to the source, sync, run, and try to
compare that run with an earlier one.

**Checkpoint.** Refused before anything is scored. A delta over different
documents reports the documents' difference as the change's effect, which is
exactly the mistake that makes a prompt look like an improvement.

## Task 5 — what is not scored

Delete `affected_systems` from one gold file and eval again.

**Checkpoint.** That document's `affected_systems` is simply not scored — not
counted as wrong, not counted as right. Absent is not `null`: `null` is a human
saying the document does not state it, absent is a human not having looked
(R7.3). Watch the field's percentage change and reason about why.

---

## Done when

- a gold set you have read line by line and would defend;
- a run scored, a second run compared, and a refusal you caused on purpose;
- you can explain each of the five rows in task 3's table without looking.

**Next:** [06 · Grounding, abstention and the one retry](../06-grounding-abstention-and-the-one-retry/).
