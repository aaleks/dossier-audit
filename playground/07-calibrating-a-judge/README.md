# 07 · Calibrating a judge

**You will build:** a free-text field nobody can score with `==`, a sample of
human-scored cases, an agreed threshold, and a calibrated judge — then watch
`dossier eval` refuse to quote it, four different ways.

**You will learn:** why a judge has to be measured before its numbers may be
printed, what a calibration sample is and why it is not a gold set, what makes a
calibration stale, why a verdict is cached like any other artifact, and what an
agreement figure does not say.

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

**Checkpoint.** Two lines per judged field: the agreement, the case count and the
judge it measured, and under them what that agreement does not say — task 7 is
about that second line. Then read `gold/incidents/calibrations/root_cause.json` and
work out what each of its fields is for. Three of them are what make the
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

In a copy of `resources/replies-judge.json`, flip the `supported` in the reply for
`rc-04` — a candidate the reviewer marked unsupported. Point the stub at the copy,
delete the calibration and the judge cache, and re-calibrate.

**Checkpoint.** 95% over twenty cases — and with a threshold of 0.95 the field is
still reported. Flip a second one, `rc-01`, which the reviewer marked supported,
and it is not. Now you have seen both sides of the bound you set in task 3, and
you know what a single disagreement costs at N=20. That is the argument the
threshold's comment is making.

## Task 7 — what the agreement does not say

Every calibration you ran printed a second line under its agreement (R7.29). Put
the three from tasks 3 and 6 side by side, and read `root_cause.json` again.

**Checkpoint.** At 100%:

```
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
```

and the same figures in the file, where `lower_bound` is not rounded.

- The lower bound at 100% is 83.9%, and the bar you set in task 3 is 0.95. Is
  this judge below your bar? Which of the figures does the gate compare, and why
  is changing that a decision for a person rather than for `dossier`?
  (R7.26 row 4, R7.5.)
- In task 6, which flip moved the `unsupported` count and which moved `supported`?
  Given what a judge exists to catch, which of the two would you rather it got
  wrong? (R7.28, R7.12.)
- A judge that answers "supported" to all twenty: work out its agreement, its
  kappa and its two counts from the sample, before checking R7.27 row 2. What
  does the gap between its agreement and its kappa say about a judge measured by
  agreement alone?
- A sample in which every case is supported would print `no unsupported case`,
  not `8 of 8`, and `kappa not measurable`. Why is each of those the honest
  answer? (R7.27 row 4, R7.28 row 4.)

## Task 8 — a judge nobody is serving

Put the judge back as it was. Restart the stub on `resources/replies-judge.json`
rather than your copy, delete `calibrations/` and `.dossier/cache/judge/`, then
calibrate and eval once. `root_cause` is reported at 100% again.

Now stop the stub (Ctrl-C in terminal 1) and run:

```bash
dossier eval incident-audit --gold gold/incidents
rm -rf .dossier/cache/judge
dossier eval incident-audit --gold gold/incidents
dossier calibrate incident-audit --gold gold/incidents
```

**Checkpoint.** The first eval completes as before. Every verdict it needs is in
the cache, so the judge is never built (R7.18). The second eval and the
calibration each stop with one line on standard error and exit code 2:

```
incident-audit: POST http://127.0.0.1:8099/api/chat/completions failed: [WinError 10061] No connection could be made because the target machine actively refused it (after 3 attempts)
```

That is the Windows wording. On Linux or macOS the middle reads `[Errno 111]
Connection refused`.

- The first request was refused, so why were three made? (R9.17 row 4.)
- `dossier run` has always said this in one line. `calibrate` and `eval` used to
  print a Python traceback for it. What does the line give you that the
  traceback buried? And why does a bug in `dossier` still get a traceback?
  (R9.20 row 7.)
- Compare `calibrations/root_cause.json` with the one you had before the stub
  stopped. What did a calibration that measured nothing write?
- With tracking on, the record each command opened is closed `FAILED` rather
  than left `RUNNING` (R11.23). Exercise 08 sets up MLflow, so come back and see
  it there.

Start the stub again, and both commands work as before.

---

## Done when

- a judged field that is withheld, then measured, then reported;
- a sample you have read and a threshold you would defend in a review;
- you can name what makes a calibration stale, and why each of those inputs
  belongs in the staleness check;
- you can say what an agreement figure hides, and which half of a sample a judge
  is failing on, from the line under it;
- you can tell a judge nobody is serving from a bug in `dossier` by what the
  terminal shows.

**Next:** [08 · MLflow tracing end to end](../08-mlflow-tracing-end-to-end/).
