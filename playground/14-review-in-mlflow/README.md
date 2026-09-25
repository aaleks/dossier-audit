# 14 · Review in MLflow

**You will build:** a tracked run whose answers two reviewers who never run
`dossier` judge in MLflow's trace view, and a gold set that one of their verdicts
reaches, through a file you read, edit and sign.

**You will learn:** what a trace shows a reviewer and under which capture setting,
how the run points reviewers at what it doubts, what a verdict is and what MLflow
records about who left it, what `dossier review pull` reads back and writes, why
an expected value is a *candidate* and not gold, what `dossier review apply` refuses
and why it refuses all at once, and why nothing else `dossier` does can read a
verdict.

**Uses the stub model as both the extractor and the judge. Needs an MLflow server
and a browser.**

---

## Background, in one paragraph

The people who can say whether an answer is right are rarely the people who run
`dossier`. A run is already recorded to MLflow (spec 011), so spec 015 makes that
record the place they review it: each trace shows the document the step read as its
**Request** and the answer as its **Response** (R15.1), and a trace the run itself
doubts is tagged so the queue is one filter (R15.2). Reviewers leave verdicts there —
a thumbs-up or -down with a reason (**feedback**), or the value that should have
been there (an **expectation**). `dossier review pull` reads them back into two files
(R15.3, R15.4), and `dossier review apply` makes an expected value gold, signed by a
maintainer (R7.7). The sentence to keep hold of: open-source MLflow records every
verdict left in its trace view as the author `User`, whoever left it — so a verdict
is evidence, never a signature, and nothing a reviewer says reaches a score until a
person with a name applies it (R15.5).

---

## Setup

This exercise gets a server of its own. `dossier review pull` reads every trace in
the pipeline's run experiment, and exercises 08 and 13 left runs of
`incident-audit` in theirs.

```bash
# from the repository root
mkdir -p playground/work/14-server
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/14-server/mlflow.db \
  --artifacts-destination file://$PWD/playground/work/14-server/mlartifacts \
  --host 127.0.0.1 --port 5114
```

The stub answers from exercise 07's rules, with this exercise's override in front.
`resources/replies-doubts.json` changes two answers so the run has something to
doubt: `PLAY-1001`'s `loss_amount` quotes the note with a comma where it has an
apostrophe, and `PLAY-1003` paraphrases its `loss_amount` and gives its
`root_cause` no source at all. Read its comment before you start.

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/14-review-in-mlflow/resources/replies-doubts.json \
  --replies playground/07-calibrating-a-judge/resources/replies-judge.json \
  --replies playground/07-calibrating-a-judge/resources/replies.json \
  --port 8114 --log playground/work/14-server/calls.jsonl
```

Build the workspace from exercise 07's material — the five notes, the verified
answers, the judge's rubric, its sample and its bar — in `playground/work/14/`, and
copy `solution/workspace/.env.example` to its `.env`:

```
DOSSIER_OPENAI_URL=http://127.0.0.1:8114/api
DOSSIER_OPENAI_API_KEY=stub
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=http://127.0.0.1:5114
DOSSIER_MLFLOW_CAPTURE=full
```

Then `sync` and `calibrate` once, and make the workspace a git repository, so that
every file review touches shows up in `git diff`:

```bash
dossier sync incident-audit
dossier calibrate incident-audit --gold gold/incidents
git init -q && printf '.dossier/\nruns/\n.env\n' > .gitignore
git add -A && git commit -qm "the workspace, before review"
```

`resources/leave_verdicts.py` leaves the reviewers' verdicts through MLflow's API,
with the same calls the trace view makes — so every task can be finished without a
browser, and the UI tasks can be checked after doing them by hand. Read its
docstring now; you will run it in tasks 4, 6 and 8.

**The people.** `s.brunner` and `j.okafor` review the daily run and never run
`dossier`. You are the maintainer: wherever this exercise says `--verified-by
<your name>`, it means yours. The solution uses `a.aleks`.

---

## Task 1 — a trace a reviewer can read

```bash
dossier run incident-audit          # this is run A
```

**Checkpoint.**

```
  extract: 5 document(s) · 0 from cache · 0 failed · 3 finding(s) · tokens not reported
    PLAY-1001.md  loss_amount: span not found in PLAY-1001.md (R6.4).
    PLAY-1003.md  loss_amount: span not found in PLAY-1003.md (R6.4).
    PLAY-1003.md  root_cause: has a value and no source. ...
```

Open `http://127.0.0.1:5114`, the experiment `dossier-audit/incident-audit/run`,
and its **Traces** tab. Five rows, named `extract · PLAY-1001.md` and so on. Read the
**Request** and **Response** columns, then open `PLAY-1001.md`'s trace.

- The Request is `{"document": "PLAY-1001.md", "inputs": {"documents": "<document
  key=…>…"}}`. Why the document the step was handed, and not the rendered prompt?
  Where is the prompt, if you want it? (R15.1, exercise 08 task 4.)
- Why is the document under `inputs` of its own, beside the key, rather than beside
  `document`? What would a step called `document` have done otherwise? (R15.1.)
- Compare the Response with `runs/<run-a>/extract/PLAY-1001.md.json`. Which is the
  answer a reviewer is judging? (R15.1, R0.11.)
- `.env` says `DOSSIER_MLFLOW_CAPTURE=full`. Predict what the two columns hold under
  `hashes`. You will check in task 9.

## Task 2 — the queue

In the trace list's search box, type:

```
tags.`dossier.review` = 'needed'
```

**Checkpoint.** Two traces: `PLAY-1001.md`, with `dossier.findings` =
`loss_amount: ungrounded`, and `PLAY-1003.md`, with
`loss_amount: ungrounded; root_cause: invalid`.

Copy the page's URL and open it in a private window. The filter came with it: a
queue is a link you can post in a channel.

- The run printed three findings and the queue holds two traces. Why?
- Why are the fields named sorted by field, rather than in the order the model
  answered them? (R15.2 row 3, R0.4.)
- `PLAY-1005`'s `root_cause` is `null`. Why is its trace not in the queue — and
  would a field `described` from a picture be (exercise 10)? (R15.2 rows 5-6, R6.5.)
- `PLAY-1002` is not in the queue either. Does that mean nobody should read it?

## Task 3 — a verdict, left by hand

You are `s.brunner`. Clear the filter and open `extract · PLAY-1002.md`, which the
run was sure of. Read the note in the Request and the answer in the Response.

The note labels the incident `minor`, and so does the answer. `s.brunner` knows the
reporting SLA, and it rates a missed reporting window `major`. In the trace's
assessments, choose **Add feedback**:

| Name | Type | Value | Rationale |
|---|---|---|---|
| `severity` | Boolean | false (no) | `Two dashboards a day stale for a business morning is a missed reporting window, which the reporting SLA rates major, not minor.` |

Then **Add expectation**:

| Name | Value |
|---|---|
| `severity` | `major` |

Now filter the trace list on the thumbs-down instead of the tag:

```
feedback.`severity` = 'false'
```

**Checkpoint.** `PLAY-1002.md` alone. Open it: both verdicts are there, and the
page names who left them as **`User`**.

- You never logged in. Would a server with authentication have recorded your name?
  What does that make a verdict, and who must sign what enters gold? (spec 015,
  "What open-source MLflow offers"; R15.4.)
- You named the feedback `severity`, not `wrong severity`. What does the name decide?
  (spec 015, "Names a reviewer uses".)
- The answer `minor` is grounded: the note says it in so many words. Can a grounded
  answer be wrong? Whose decision is it? (R6.4, R7.7.)

## Task 4 — the other reviewers, through the API

```bash
.venv/bin/python playground/14-review-in-mlflow/resources/leave_verdicts.py \
  http://127.0.0.1:5114
```

**Checkpoint.** The queue printed first, as in task 2. Then your two verdicts from
task 3 reported `already`, and five `left`:

- `s.brunner` gives `PLAY-1001`'s `loss_amount` a thumbs-down — logged through the
  API under their own name, not `User`;
- `j.okafor` expects `severity` `critical` for `PLAY-1002`, where `s.brunner`
  expected `major`;
- `j.okafor` expects a `summary` for `PLAY-1002`, which the pipeline has no field for;
- `j.okafor` expects `severity` `catastrophic` for `PLAY-1003`;
- `j.okafor` gives `PLAY-1004` an `overall` thumbs-up.

Reload the trace list and find `s.brunner`'s name on one verdict among the
`User`s.

- What made the difference, and what will `dossier` report as the author of each?
  (R15.3 row 5.)
- Predict which of the seven will become gold candidates, and which of those
  `dossier review apply` will refuse.

## Task 5 — pull

```bash
dossier review pull incident-audit
```

**Checkpoint.**

```
incident-audit  7 verdicts on 1 run
  extract  loss_amount  0 yes · 1 no
      PLAY-1001.md  s.brunner: The quoted span is not in the note, which writes CHF 18'400, not 18,400.
  extract  overall  1 yes · 0 no
  extract  severity  0 yes · 1 no · 3 values expected
      PLAY-1002.md  User: Two dashboards a day stale for a business morning is ...
  extract  summary  1 value expected
written to review/incident-audit/feedback.jsonl
4 expected values written as gold candidates to review/incident-audit/candidates.jsonl
```

Read both files, commit them, and pull again:

```bash
git add review && git commit -qm "review: first pull"
dossier review pull incident-audit
git status --short
```

**Checkpoint.** `git status` prints nothing.

- Three feedbacks are in `feedback.jsonl`, and none is in `candidates.jsonl`. Why can
  a thumbs-down never become a candidate, however clear its reason? (R15.4 row 1.)
- Every candidate's `reason` is `null`. Where did `s.brunner`'s reason go, and why
  does the maintainer need both files?
- The file is the whole set every time, not what is new since the last pull. What
  does that buy you, given the commit you just made? (R15.3 row 4.)

Now score the run, and pull once more:

```bash
dossier eval incident-audit --gold gold/incidents
dossier review pull incident-audit
git status --short
```

**Checkpoint.** `severity 100.0%`, `root_cause 80.0% (3 judged)`, three judge calls in
the stub's log — and `git status` still prints nothing.

- Two reviewers say `PLAY-1002` is not `minor`, and `severity` scored 100%. Why is
  that right? (R15.5 row 4.)
- The eval recorded three of the judge's verdicts to MLflow as assessments (R11.16).
  Why did the pull not read them? If every command recorded to one experiment
  (exercise 08, task 2), would it have? (R15.3 row 3.)

Last, `DOSSIER_MLFLOW_ENABLED=false dossier review pull incident-audit`.

**Checkpoint.** Exit 2, naming the variable, nothing written. Why is this command
refused with tracking off, where `dossier run` just runs without a record? (R15.3
row 6.)

## Task 6 — a verdict overridden, and one the page would edit in place

You are `j.okafor`. Open `extract · PLAY-1001.md` and find `s.brunner`'s
thumbs-down on `loss_amount`. You read the note: CHF 18'400 is exactly the figure
its Impact section states, and only the quote is wrong. You want to say so where
the thumbs-down is.

Open that verdict's menu (⋮): it offers **Delete**, and no **Edit**. Now open the
menu on the `severity` thumbs-down on `PLAY-1002.md`, which you did not leave
either: it offers both.

The page shows Edit only on a verdict whose author is the user it thinks you
are — and it thinks everyone is `User`. `s.brunner`'s verdict on `PLAY-1001`
carries a real name, so the page will not change it. What replaces it is an
**override**: a new verdict that names the old one, which MLflow then marks as
overridden. The page offers overrides only on feedback no person left, such as a
judge's, so this one goes through the API:

```bash
.venv/bin/python playground/14-review-in-mlflow/resources/leave_verdicts.py \
  http://127.0.0.1:5114 --override
```

Then pull, and look at what changed:

```bash
dossier review pull incident-audit
git diff review
```

**Checkpoint.** `extract  loss_amount  1 yes · 0 no`, and exactly one line of
`feedback.jsonl` replaced: `s.brunner`'s `false` out, a `true` by `User` in, under a
new assessment id.

- Reload the trace. `s.brunner`'s thumbs-down is still there, marked as overridden.
  Why does the pull read only the override? (R15.3 row 2.)
- Had you pressed Edit on `PLAY-1002`'s `severity` thumbs-down and saved `true`,
  nothing would have been overridden: the page changes a `User` verdict in place,
  under the same id, and MLflow keeps no earlier value. What would `git diff review`
  have shown after the next pull? Where, then, is the only record that it once said
  `false`? (spec 015, "What open-source MLflow offers".)
- `s.brunner` and `j.okafor` are both right, about different things. What is each
  right about — and does the gold set need to change? Where does the fix go instead?
  (R6.4, R7.4.)

## Task 7 — apply, refused

Commit what the pull wrote, then try to make the candidates gold — first without a
name, then with yours:

```bash
git add review && git commit -qm "review: the override"
dossier review apply incident-audit --gold gold/incidents
dossier review apply incident-audit --gold gold/incidents --verified-by <your name>
git status --short
```

**Checkpoint.** Exit 2 both times. The first names `--verified-by`. The second names
three problems at once:

```
incident-audit: nothing applied:
  PLAY-1002.md summary: summary is not a field the pipeline declares; ...
  PLAY-1003.md severity: 'catastrophic' is not one of minor, major, critical
  PLAY-1002.md severity: reviewers expected different values: 'major' (User, tr-…), 'critical' (User, tr-…)
```

and `git status` prints nothing: not one gold file was written.

- `major` for `PLAY-1002` is a perfectly good candidate. Why is it not applied on its
  own while the other three are sorted out? (R15.4.)
- Both conflicting candidates say `User`. How would you find out who to ask?
- Every candidate already names an author. Why is `--verified-by` still required,
  and why is it checked before a single file is read? (R15.4 row 9, R7.7.)

## Task 8 — the maintainer's edit, and the signature

You settle `PLAY-1002` with both reviewers: the SLA says `major`. Open
`review/incident-audit/candidates.jsonl` and **delete** three lines — `critical`,
`summary` and `catastrophic` — leaving `major`. Then:

```bash
git diff --stat
dossier review apply incident-audit --gold gold/incidents --verified-by <your name>
git diff gold
dossier eval incident-audit --gold gold/incidents
dossier review apply incident-audit --gold gold/incidents --verified-by <your name>
```

**Checkpoint.**

```
  PLAY-1002.md  severity  'minor' -> 'major'
1 answer applied to gold/incidents, signed by <your name>
```

`git diff gold` shows `PLAY-1002.json`'s `severity` as `major`, with your name, today's
date, a `reason` naming the trace and `User`, and `"superseded": "minor"`. The eval
scores `severity 80.0%`, `PLAY-1002.md 'minor' does not match 'major'`, with no model
call. The second apply says `nothing to apply: every candidate is already gold`.

- Who signed the answer, and where did `s.brunner` and their trace end up? Why is the
  old value kept? (R15.4 row 2, R7.7.)
- The same run, the same answers, and `severity` went from 100% to 80%. What changed?
  Now read the pull's report again: where does the work to get that point back
  start? (spec 015, Purpose.)

Commit, and pull again:

```bash
git add gold review && git commit -qm "PLAY-1002 severity: major, from review"
dossier review pull incident-audit
git diff --stat
```

**Checkpoint.** `candidates.jsonl | 3 +++`: the three lines you deleted are back.

- Why is that right, rather than a bug? Where does a candidate get rejected *for
  good*? (R15.4 row 8.)

Reject them where they were left: in each trace, **Delete assessment** on the
`critical`, `summary` and `catastrophic` expectations — or:

```bash
.venv/bin/python playground/14-review-in-mlflow/resources/leave_verdicts.py \
  http://127.0.0.1:5114 --reject
dossier review pull incident-audit
git diff --stat
dossier review apply incident-audit --gold gold/incidents --verified-by <your name>
```

**Checkpoint.** `4 verdicts on 1 run`; `candidates.jsonl` back to the one line you
committed, so only `feedback.jsonl | 3 ---` differs; and `nothing to apply`.

## Task 9 — nothing else reads a verdict, and a server nobody can review

Commit, then run twice more — once as before, once with the documents kept off the
server:

```bash
git add review && git commit -qm "review: rejected for good"
dossier run incident-audit                                   # run B
DOSSIER_MLFLOW_CAPTURE=hashes dossier run incident-audit     # run C
diff -r runs/<run-a>/extract runs/<run-b>/extract
diff -r runs/<run-a>/extract runs/<run-c>/extract
```

**Checkpoint.** `5 from cache` both times, no model call, both `diff`s empty. The
queue now holds six traces, two from each run.

Open `extract · PLAY-1002.md` from each of the three runs.

- Run B's trace has the same Request and Response as run A's (R15.1 row 3) and none of
  the verdicts. Where are they, and will the next pull still find them?
- Clear `dossier.review` on run A's `PLAY-1001` trace (**Edit tags**), as a reviewer
  who is done with it would. Run B's trace of it is tagged all the same. Why is that
  right? (R15.2 row 4.)
- Run C's Request is the key and a 64-character hash; its Response is
  `{"artifact": "<sha256>"}`. What can a reviewer judge from that? Who could check
  those hashes, and who could not? Why does `dossier` not switch to `full` for the
  runs a reviewer needs? (R15.1 row 6, R10.8.)
- Verdicts sat on the server all through runs B and C. Name what a verdict could
  have changed about a run — a key, the manifest, an artifact, a score — and say for
  each why it did not. (R15.5.)

---

## Done when

- a run whose traces show a reviewer the document and the answer, and a queue of the
  two it doubted, shared as a link;
- a verdict you left by hand, recorded as `User`, and one logged under a real name;
- a pull that wrote every valid human verdict, and a second pull `git` could not tell
  from the first;
- an override read as the override, and the thumbs-down it replaced left out;
- an apply refused without a name, and refused again naming three problems at once,
  with no gold file touched;
- a candidate you kept, signed and applied — the value it replaced kept beside it —
  and three you rejected, first for one apply and then for good;
- a score that moved because gold did, and a run that no verdict could move.

**Back to:** [the playground index](../README.md).
