# 07 · Calibrating a judge

**You will build:** a free-text field nobody can score with `==`, a sample of
human-scored cases, an agreed threshold, and a calibrated judge — then watch
`dossier eval` refuse to quote it, four different ways.

**You will learn:** why a judge has to be measured before its numbers may be
printed, what a calibration sample is and why it is not a gold set, what makes a
calibration stale, and why a verdict is cached like any other artifact.

**Uses the stub model as both the extractor and the judge.**

---

## Background, in one paragraph

Some fields have no `==`. "Was this the root cause?" is decided by reading the
document, so `dossier` asks a model — a judge — and then has a problem: a judge
that has never been shown to agree with a human still produces a percentage, and
that percentage reads exactly like evidence. Everything in this exercise exists to
tell the two apart. A judged field declares a rubric; the gold set declares the
agreement its judge must reach; `dossier calibrate` measures the judge against a
sample of human-scored cases and writes down what it measured; and `dossier eval`
prints the field's score only if all of that lines up (R7.13–R7.19).

---

## Task 1 — a field that needs a judge

Start from a copy of your exercise 05 workspace. Add to the field declaration:

```yaml
  root_cause:       {kind: free_text, judge: rubrics/root_cause.md}
```

and write `pipelines/incident-audit/rubrics/root_cause.md`. Keep it to the one
question the judge will be measured on — the rubric is passed to the judge as you
wrote it, and nothing `dossier` adds may raise or lower the standard it sets.

Add the fifth note, `resources/documents/PLAY-1005.md`, to `inbox/incidents/`:
an incident whose cause was never determined. You will see why it earns its place
in task 4.

Copy the five gold proposals from `resources/verified-answers/` into
`gold/incidents/` — they now carry a `root_cause` too, including `PLAY-1005`'s
`null`.

Sync, run (with `resources/replies.json` as the stub's rules), and eval.

**Checkpoint.**

```
  root_cause             -- never measured -- run `dossier calibrate`
```

Named, not omitted, and not printed as zero. A missing line would read as a field
nobody verified, which is a different problem wanting different work (R7.15).

## Task 2 — the sample, and why it is not the gold set

Read `resources/calibration-sample/root_cause.jsonl`. Twenty cases, each one a
*candidate answer* and a human's verdict on whether the document supports it:

```json
{"id": "rc-04", "document": "PLAY-1001.md",
 "answer": "The payment gateway vendor had an outage during the window.",
 "supported": false, "reason": "…", "verified_by": "a.aleks", "verified_at": "2026-09-17"}
```

Before copying it into `gold/incidents/samples/`, answer these:

- Why can this not live in the gold files? A gold file says what the right value
  *is*; what does a sample line say?
- Twelve of the twenty are `supported`. What would a judge that answers
  "supported" to everything score on this sample — and what does that tell you
  about where a threshold may not be set?
- Why does the minimum sample size exist at all, and what should a report say
  below it?

## Task 3 — the threshold, and who gets to write it

Read `resources/judge-threshold/judge.yaml`, including the comment, and decide
whether you agree with 0.95. Then write your own into `gold/incidents/judge.yaml`
with your name and today's date.

This is the one number in the system nobody may invent — not `dossier`, not an
assistant, not a future you in a hurry. `dossier calibrate` may write what it
*measured* and may never touch this file: a run able to move the bar it is judged
against would be a judge grading its own paper (R7.14).

Now calibrate:

```bash
dossier calibrate incident-audit --gold gold/incidents
```

**Checkpoint.** One line per judged field: the agreement, the case count, and the
judge it measured. Then read `gold/incidents/calibrations/root_cause.json` and
work out what each of its five fields is for. Two of them are what make the
measurement go stale later — find them before task 5 tells you.

## Task 4 — the field is reported

```bash
dossier eval incident-audit --gold gold/incidents
```

**Checkpoint.**

```
  root_cause         100.0%   (4 judged)
```

Five documents, four judged. Find the fifth and explain it — the answer is what
`PLAY-1005` is doing in this exercise, and it is R7.17's "the judge decides only
what is left".

Then run `eval` again and watch the stub's call log.

**Checkpoint.** Not one extra call. A verdict is an artifact in the `judge` cache
namespace, content-addressed like any stage's, so a second eval of the same run
asks nothing (R7.18). Find the entries under `.dossier/cache/judge/`.

## Task 5 — four ways to lose the right to print a number

Do each of these, eval after each, and put the message back before the next:

1. Append a sentence to `rubrics/root_cause.md`.
2. Change `model:` in `pipeline.yaml` to another pinned identifier.
3. Raise the threshold in `judge.yaml` above what you measured.
4. Delete `gold/incidents/calibrations/root_cause.json`.

**Checkpoint.** Four different messages, because they want four different fixes.
One of them is worth extra thought: what exactly changed in case 1, given that
the judge, the sample and the threshold are all untouched?

Then, the sharpest question in this exercise: **at exactly the threshold, is the
field reported?** Set the bar to precisely what you measured and find out. Then
find the line of code that decides it and the sentence in the spec that says it
must be that way.

## Task 6 — make the judge wrong, on purpose

Flip one `supported` in `resources/replies-judge.json`, delete the calibration and
the judge cache, and re-calibrate.

**Checkpoint.** 95% over twenty cases — and with a threshold of 0.95 the field is
still reported. Flip a second one and it is not. Now you have seen both sides of
the bound you set in task 3, and you know what a single disagreement costs at
N=20. That is the argument the threshold's comment is making.

---

## Done when

- a judged field that is withheld, then measured, then reported;
- a sample you have read and a threshold you would defend in a review;
- you can name what makes a calibration stale, and why each of those inputs
  belongs in the staleness check.

**Next:** [08 · MLflow tracing end to end](../08-mlflow-tracing-end-to-end/).
