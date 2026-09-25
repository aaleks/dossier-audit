# 14 · Solution

Every command below was run against this repository in one pass, starting from an
empty MLflow 3.15.1 server with a SQLite backend. The output shown is what it
produced, with five liberties taken in how it is shown:

- The workspace's absolute path is shortened to `…` and written with `/`.
- MLflow's own log lines are left out, since they are MLflow talking, not `dossier`.
- What the trace list shows is quoted from the same data, read with
  `MlflowClient.search_traces`, and cut at the end of a line.
- Task 3's two verdicts were posted to the endpoint the trace view posts to, with
  the body its **Add feedback** and **Add expectation** send — source `HUMAN`,
  author `User` — because a transcript cannot click.
- The menus task 6 describes are read from the page's JavaScript, not from a
  screenshot.

## Run the prepared answer

Terminal 1 — MLflow, with a database of its own:

```bash
mkdir -p playground/work/14-server
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/14-server/mlflow.db \
  --artifacts-destination file://$PWD/playground/work/14-server/mlartifacts \
  --host 127.0.0.1 --port 5114
```

Terminal 2 — the stub, with this exercise's two doubtful answers in front of
exercise 07's rules:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/14-review-in-mlflow/resources/replies-doubts.json \
  --replies playground/07-calibrating-a-judge/resources/replies-judge.json \
  --replies playground/07-calibrating-a-judge/resources/replies.json \
  --port 8114 --log playground/work/14-server/calls.jsonl
```

Terminal 3 — exercise 07's material, with this exercise's `.env`, and every step
of the review, with the script standing in for the reviewers:

```bash
W=playground/work/14
V="$PWD/.venv/bin/python $PWD/playground/14-review-in-mlflow/resources/leave_verdicts.py"
mkdir -p $W/inbox/incidents $W/gold/incidents/samples
cp -r playground/07-calibrating-a-judge/solution/workspace/. $W/
cp playground/corpus/incidents/PLAY-100[1-4].md $W/inbox/incidents/
cp playground/07-calibrating-a-judge/resources/documents/PLAY-1005.md $W/inbox/incidents/
cp playground/07-calibrating-a-judge/resources/verified-answers/*.json $W/gold/incidents/
cp playground/07-calibrating-a-judge/resources/calibration-sample/root_cause.jsonl \
   $W/gold/incidents/samples/
cp playground/07-calibrating-a-judge/resources/judge-threshold/judge.yaml \
   $W/gold/incidents/judge.yaml
cp playground/14-review-in-mlflow/solution/workspace/.env.example $W/.env

cd $W
dossier sync incident-audit
dossier calibrate incident-audit --gold gold/incidents
dossier run incident-audit
$V http://127.0.0.1:5114              # every reviewer's first pass
$V http://127.0.0.1:5114 --override   # j.okafor overrides s.brunner
$V http://127.0.0.1:5114 --reject     # the three candidates rejected for good
dossier review pull incident-audit
dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks
dossier eval incident-audit --gold gold/incidents
```

The last three commands end the way task 8 does. The pull reads `4 verdicts on 1
run` and one expected value. The apply sets `PLAY-1002.md  severity  'minor' ->
'major'`, signed `a.aleks`. The eval scores `severity 80.0%` and `overall 84.0%`.

Below, the exercise itself, task by task. `dossier` runs inside the workspace and
`leave_verdicts.py` from the repository root, as the README shows; below, the
latter is written `python leave_verdicts.py`. The setup's `sync` and `calibrate`:

```
incidents-manual  0 known · 0 changed · 5 new -> 5 fetched
ledger updated · 5 new snapshots · 0 tombstoned

root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
recorded to MLflow: dossier-audit/incident-audit/calibrate
```

---

## Task 1 — a trace a reviewer can read

```
$ dossier run incident-audit
run 20260925T103248Z-ee27 · …/runs/20260925T103248Z-ee27/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260925T103248Z-ee27
  extract: 5 document(s) · 0 from cache · 0 failed · 3 finding(s) · tokens not reported
    PLAY-1001.md  loss_amount: span not found in PLAY-1001.md (R6.4).
    PLAY-1003.md  loss_amount: span not found in PLAY-1003.md (R6.4).
    PLAY-1003.md  root_cause: has a value and no source. A figure without evidence is the thing this system exists not to produce (R6.6).
```

The trace list, `PLAY-1001.md`'s row:

```
extract · PLAY-1001.md
  Request   {"document": "PLAY-1001.md", "inputs": {"documents": "<document key=\"PLAY-1001.md\"># PLAY-1001 — Checkout timeouts after the payment gateway upgrade\n\n**Severity:** major\n**Resolved:** 2026-03-04 …
  Response  {"document": "PLAY-1001.md", "fields": [{"field": "loss_amount", "value": 18400.0, "currency": "CHF", "reason": null, "confidence": "high", "source": {"document": "PLAY-1001.md", "span": "a recorded loss of CHF 18,400", "page": null}}, …
```

**Why the document, and not the prompt.** A reviewer judges an answer against
what it was taken from. The prompt is the same template on every trace; what
differs from one row to the next is the document, so that is what the Request
shows. The rendered prompt is still there, one level down, on the LLM span the
step's call made (exercise 08, task 4). The Request is the document as the step
was handed it: the input's value, wrapped in the `<document>` tag the prompt
renders it in (R15.1, R3.13).

**Why `inputs` of its own.** The trace's key sits under `"document"`. The step's
inputs are named by whoever writes the pipeline, and nothing stops one of them
being called `document`. Placed beside the key, that input would have replaced
the key, or the key would have replaced it. Placed under `inputs`, the two can
never collide (R15.1).

**Which answer is judged.** The Response is `runs/20260925T103248Z-ee27/extract/PLAY-1001.md.json`,
parsed: the two compare equal. It is not the model's reply. The stub replied
without `reason` or `page`, and the Response has both, as `null`, because it is
the validated field record — the one `runs/` holds and `dossier eval` scores
(R15.1, R0.11). A reviewer judges the answer `dossier` kept, not the text it was
given.

**Under `hashes`**, predicted here and seen in task 9: the Request holds the key
and the document's sha256, and the Response holds the artifact's sha256.

---

## Task 2 — the queue

```
tags.`dossier.review` = 'needed'      2 traces

extract · PLAY-1001.md   dossier.findings  loss_amount: ungrounded
extract · PLAY-1003.md   dossier.findings  loss_amount: ungrounded; root_cause: invalid
```

**Three findings, two traces.** A finding is about one field, and a trace is
about one (step, document). `PLAY-1003` has two doubtful fields on one trace, and
the tag names both.

**Sorted by field.** The model answered `loss_amount` before `root_cause`, but
another model, or the same one on another day, could answer in any order. The
tag is sorted, so the same doubts always give the same string (R15.2 row 3, R0.4).
Two things depend on that. A filter on the value finds every trace with those
doubts. And a run served from cache tags exactly what the first run tagged
(R15.2 row 4).

**`PLAY-1005` is not in the queue.** Its `root_cause` is `null` with a reason:
the note says the cause is undetermined, so abstaining is the right answer, not a
doubt (R6.5, R15.2 row 5). A field `described` from a picture would not be queued
either. It is a third grounding state, and the judge decides it (R15.2 row 6,
R6.15, exercise 10).

**`PLAY-1002` is not in the queue either.** That does not mean nobody should read
it. The queue lists what the run doubted, not what is wrong. Anything the run was
sure of is still one click away with the filter cleared, and task 3 finds a wrong
answer there.

---

## Task 3 — a verdict, left by hand

```
feedback.`severity` = 'false'      1 trace

extract · PLAY-1002.md
  severity   feedback     false    User   Two dashboards a day stale for a business morning is a …
  severity   expectation  'major'  User
```

**A server with authentication would record the same thing.** The trace view does
not ask the server who is logged in. Its current user is a constant in the
JavaScript it ships, `const r=()=>"User"`, and it sends that as the author of
every verdict. A verdict is therefore evidence of what someone thought, and
signed by no one. What enters gold is signed by the maintainer who applies it
(spec 015, "What open-source MLflow offers"; R15.4).

**The name decides where a verdict goes.** Named after a field, `severity`, the
feedback is counted against that field in the pull's report. An expectation named
after a field becomes a gold candidate for that field. Named `wrong severity`, the
feedback would be a remark about the whole answer: counted in the report under
its own name, and never gold (spec 015, "Names a reviewer uses").

**A grounded answer can be wrong.** Grounding proves the value is in the document
(R6.4). It cannot prove the document is right, or that the organisation agrees
with the label someone gave the incident on the day. The note says `minor`; the
reporting SLA says a missed window is `major`. Which of the two is correct is a
decision about the definition of correct, and a named person makes it (R7.7).

---

## Task 4 — the other reviewers, through the API

```
$ python leave_verdicts.py http://127.0.0.1:5114
queue    tags.`dossier.review` = 'needed'  ·  2 traces
         PLAY-1001.md  loss_amount: ungrounded
         PLAY-1003.md  loss_amount: ungrounded; root_cause: invalid

         document      kind        name         value           author     for        trace
already  PLAY-1002.md  feedback    severity     False           User       s.brunner  tr-3d54626f09316c030dfcea0bb07b6de1
already  PLAY-1002.md  expectation severity     'major'         User       s.brunner  tr-3d54626f09316c030dfcea0bb07b6de1
left     PLAY-1001.md  feedback    loss_amount  False           s.brunner  s.brunner  tr-07328054b857c6b95709586caa0c6053
left     PLAY-1002.md  expectation severity     'critical'      User       j.okafor   tr-3d54626f09316c030dfcea0bb07b6de1
left     PLAY-1002.md  expectation summary      'The nightly e… User       j.okafor   tr-3d54626f09316c030dfcea0bb07b6de1
left     PLAY-1003.md  expectation severity     'catastrophic'  User       j.okafor   tr-fa197ad25569fb92ea73a2d7d82429c6
left     PLAY-1004.md  feedback    overall      True            User       j.okafor   tr-7c14765585192d49e25bfd3a5602b351
```

**The difference is who wrote the author field.** The API call passed
`source_id="s.brunner"`, and the page always passes `User`. MLflow stores whatever
it is sent. `dossier` reports the author MLflow holds, whatever it is, and never
invents one: `s.brunner` for that one verdict, `User` for the other six (R15.3
row 5).

**The prediction.** The four expectations become candidates: `major`, `critical`,
`summary` and `catastrophic`. The three feedbacks never do. `dossier review apply`
refuses three of the candidates — `summary` is not a field, `catastrophic` is not
a value the enum allows, and `major` and `critical` conflict — and so it applies
none of them, `major` included.

---

## Task 5 — pull

```
$ dossier review pull incident-audit
incident-audit  7 verdicts on 1 run
  extract  loss_amount  0 yes · 1 no
      PLAY-1001.md  s.brunner: The quoted span is not in the note, which writes CHF 18'400, not 18,400.
  extract  overall  1 yes · 0 no
  extract  severity  0 yes · 1 no · 3 values expected
      PLAY-1002.md  User: Two dashboards a day stale for a business morning is a missed reporting window, which the reporting SLA rates major, not minor.
  extract  summary  1 value expected
written to review/incident-audit/feedback.jsonl
4 expected values written as gold candidates to review/incident-audit/candidates.jsonl
```

`review/incident-audit/feedback.jsonl`:

```
{"assessment": "a-1d6dfd77137e41368d37cc157e79c3a5", "at": "2026-09-25T10:33:32Z", "document": "PLAY-1001.md", "kind": "feedback", "name": "loss_amount", "rationale": "The quoted span is not in the note, which writes CHF 18'400, not 18,400.", "reviewer": "s.brunner", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-07328054b857c6b95709586caa0c6053", "value": false}
{"assessment": "a-317448909a95444e84f12bcce9024618", "at": "2026-09-25T10:33:24Z", "document": "PLAY-1002.md", "kind": "feedback", "name": "severity", "rationale": "Two dashboards a day stale for a business morning is a missed reporting window, which the reporting SLA rates major, not minor.", "reviewer": "User", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-3d54626f09316c030dfcea0bb07b6de1", "value": false}
{"assessment": "a-b17d820099fc43c8bc1e57181b4fe471", "at": "2026-09-25T10:33:24Z", "document": "PLAY-1002.md", "kind": "expectation", "name": "severity", "rationale": null, "reviewer": "User", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-3d54626f09316c030dfcea0bb07b6de1", "value": "major"}
{"assessment": "a-81d6cb1bb91c451b844dcf409e5bdb4f", "at": "2026-09-25T10:33:32Z", "document": "PLAY-1002.md", "kind": "expectation", "name": "severity", "rationale": null, "reviewer": "User", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-3d54626f09316c030dfcea0bb07b6de1", "value": "critical"}
{"assessment": "a-230739bfe8a04144bc56fed726f1e5a4", "at": "2026-09-25T10:33:32Z", "document": "PLAY-1002.md", "kind": "expectation", "name": "summary", "rationale": null, "reviewer": "User", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-3d54626f09316c030dfcea0bb07b6de1", "value": "The nightly export ran past the reporting window after a late warehouse load."}
{"assessment": "a-d25b994a599d4beb981182df5e4c0ace", "at": "2026-09-25T10:33:32Z", "document": "PLAY-1003.md", "kind": "expectation", "name": "severity", "rationale": null, "reviewer": "User", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-fa197ad25569fb92ea73a2d7d82429c6", "value": "catastrophic"}
{"assessment": "a-286264dbaeca4786b015c75f62f76c80", "at": "2026-09-25T10:33:32Z", "document": "PLAY-1004.md", "kind": "feedback", "name": "overall", "rationale": "Every field is the one the note states.", "reviewer": "User", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-7c14765585192d49e25bfd3a5602b351", "value": true}
```

`review/incident-audit/candidates.jsonl`:

```
{"at": "2026-09-25T10:33:24Z", "document": "PLAY-1002.md", "field": "severity", "reason": null, "suggested_by": "User", "trace": "tr-3d54626f09316c030dfcea0bb07b6de1", "value": "major"}
{"at": "2026-09-25T10:33:32Z", "document": "PLAY-1002.md", "field": "severity", "reason": null, "suggested_by": "User", "trace": "tr-3d54626f09316c030dfcea0bb07b6de1", "value": "critical"}
{"at": "2026-09-25T10:33:32Z", "document": "PLAY-1002.md", "field": "summary", "reason": null, "suggested_by": "User", "trace": "tr-3d54626f09316c030dfcea0bb07b6de1", "value": "The nightly export ran past the reporting window after a late warehouse load."}
{"at": "2026-09-25T10:33:32Z", "document": "PLAY-1003.md", "field": "severity", "reason": null, "suggested_by": "User", "trace": "tr-fa197ad25569fb92ea73a2d7d82429c6", "value": "catastrophic"}
```

```
$ git add review && git commit -qm "review: first pull"
$ dossier review pull incident-audit
…
$ git status --short
$
```

**A thumbs-down never becomes a candidate.** It says the value is wrong, not what
the right value is, and a gold answer is a value. Only an expectation carries one
(R15.4 row 1). However clear its reason, a thumbs-down goes to the report, where
prompt work starts.

**Where the reason went.** `s.brunner`'s reason is on the feedback, a separate
verdict on the same trace. The expectation was left with no rationale, so its
candidate has none. The maintainer needs both files: `candidates.jsonl` says
what reviewers expect, and `feedback.jsonl` says why, joined by the trace id.

**The whole set each time.** Two pulls with nothing new write the same bytes, so
`git diff` after a pull is exactly what reviewers added, changed or removed since
the last commit (R15.3 row 4). As task 6 shows, that diff is also the only history
there is.

```
$ dossier eval incident-audit --gold gold/incidents
5 documents · 5 fields · overall 88.0%
  loss_amount         60.0%   <- weakest
    PLAY-1001.md   ungrounded: the value may be right, and nothing in the document shows it
    PLAY-1003.md   ungrounded: the value may be right, and nothing in the document shows it
  resolution_date    100.0%
  severity           100.0%
  affected_systems   100.0%
  root_cause          80.0%   (3 judged)
    PLAY-1003.md   root_cause: has a value and no source. A figure without evidence is the thing this system exists not to produce (R6.6).
recorded to MLflow: dossier-audit/incident-audit/eval

$ dossier review pull incident-audit
incident-audit  7 verdicts on 1 run
…
$ git status --short
$
```

The stub's log grew by three lines, from 25 to 28: the judge, asked about the
three `root_cause` values it had not seen.

**`severity` 100% is right.** Gold says `minor`, and the answer is `minor`. Two
reviewers disagree, but a candidate is not gold until someone signs it, and the
eval scores against the gold set as it is (R15.5 row 4).

**The judge's verdicts were not read.** They were recorded on the eval's traces,
in `dossier-audit/incident-audit/eval`, and the pull reads the run experiment
only. Even if both lived in one experiment, the pull would skip them: their
source is `LLM_JUDGE`, not `HUMAN`. They are the judge's verdicts, not a
reviewer's (R15.3 row 3).

```
$ DOSSIER_MLFLOW_ENABLED=false dossier review pull incident-audit
incident-audit: pulling reviews needs tracking on: set DOSSIER_MLFLOW_ENABLED=true and DOSSIER_MLFLOW_TRACKING_URI. Reviewers' verdicts are read from MLflow and nowhere else
$ echo $?
2
```

**Why refuse, when `dossier run` doesn't.** A run's record is a side effect of the
run. The run's own work is in `runs/`, and happens without a record. A pull's only
input is the server. With tracking off it could only report no verdicts, which
says "no reviewer disagreed" when nobody was asked (R15.3 row 6).

---

## Task 6 — a verdict overridden, and one the page would edit in place

**The menus.** The trace view decides whether to show **Edit** by comparing the
verdict's author with its own user, which is always `User`. It shows Edit for a
`User` verdict, and for feedback no person left. So `s.brunner`'s
`loss_amount` verdict, logged under a real name, gets **Delete** only.
`PLAY-1002`'s `severity` thumbs-down, left through the page, gets both. When the
page does edit, it sends a `PATCH` to the verdict itself. It sends an override
only for feedback whose author is not `User`, which through the page means a
judge's.

```
$ python leave_verdicts.py http://127.0.0.1:5114 --override
override PLAY-1001.md  feedback    loss_amount  True            User       j.okafor   tr-07328054b857c6b95709586caa0c6053
         of a-1d6dfd77137e41368d37cc157e79c3a5, left by s.brunner: now invalid

$ dossier review pull incident-audit
incident-audit  7 verdicts on 1 run
  extract  loss_amount  1 yes · 0 no
  extract  overall  1 yes · 0 no
  extract  severity  0 yes · 1 no · 3 values expected
      PLAY-1002.md  User: Two dashboards a day stale for a business morning is a missed reporting window, which the reporting SLA rates major, not minor.
  extract  summary  1 value expected
written to review/incident-audit/feedback.jsonl
4 expected values written as gold candidates to review/incident-audit/candidates.jsonl

$ git diff review
--- a/review/incident-audit/feedback.jsonl
+++ b/review/incident-audit/feedback.jsonl
@@ -1,4 +1,4 @@
-{"assessment": "a-1d6dfd77137e41368d37cc157e79c3a5", "at": "2026-09-25T10:33:32Z", "document": "PLAY-1001.md", "kind": "feedback", "name": "loss_amount", "rationale": "The quoted span is not in the note, which writes CHF 18'400, not 18,400.", "reviewer": "s.brunner", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-07328054b857c6b95709586caa0c6053", "value": false}
+{"assessment": "a-98d8f43f46f8479b87911b1b6cbef5b9", "at": "2026-09-25T10:34:15Z", "document": "PLAY-1001.md", "kind": "feedback", "name": "loss_amount", "rationale": "The value is right: CHF 18'400 is the figure the Impact section states. Only the quote is off, by one character.", "reviewer": "User", "run": "20260925T103248Z-ee27", "step": "extract", "trace": "tr-07328054b857c6b95709586caa0c6053", "value": true}
 {"assessment": "a-317448909a95444e84f12bcce9024618", …
```

**Only the override is read.** An override is the reviewer's current position,
and the verdict it overrode is marked invalid. Reading both would count one
question twice, once each way. The pull keeps valid verdicts only (R15.3 row 2).
The trace view keeps the old one visible, marked as overridden, for anyone who
wants to know what changed.

**An edit in place leaves no trace but yours.** A `PATCH` keeps the verdict's id
and its creation time, which is the `at` the pull writes, and replaces its value
and rationale. After the next pull, `git diff review` would have shown the same
line — same assessment id, same `at` — with `false` turned to `true` and the
rationale rewritten. MLflow keeps no earlier value and no name for the change.
The only record that it once said `false` is the `feedback.jsonl` you committed
in task 5. This was checked live, against a scratch trace, rather than on this
exercise's: the `PATCH` the page sends returned 200, the verdict kept its id, and
no override was written.

**Both reviewers are right, about different things.** `s.brunner` is right that
the quote is not in the note, so the field is ungrounded, and `dossier` scores it
incorrect even though the value matches gold (R6.4, R7.4). `j.okafor` is right
that the value, CHF 18'400, is correct. Gold already says `18400`, so gold does
not change. The fix belongs where the answer came from: the extraction prompt must
make the model quote the note verbatim. Here, that means the reply file.

---

## Task 7 — apply, refused

```
$ git add review && git commit -qm "review: the override"
$ dossier review apply incident-audit --gold gold/incidents
incident-audit: --verified-by is required: there is no anonymous path into the gold set (R7.7). MLflow's trace view records every reviewer as User, so the maintainer who applies a candidate signs it
$ echo $?
2

$ dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks
incident-audit: nothing applied:
  PLAY-1002.md summary: summary is not a field the pipeline declares; a verdict about the whole answer is the report's, never gold's
  PLAY-1003.md severity: 'catastrophic' is not one of minor, major, critical
  PLAY-1002.md severity: reviewers expected different values: 'major' (User, tr-3d54626f09316c030dfcea0bb07b6de1), 'critical' (User, tr-3d54626f09316c030dfcea0bb07b6de1)
$ echo $?
2

$ git status --short
$
```

**Why `major` waits.** Applying the candidates that pass while the rest are
sorted out would write a gold set half-applied. Nobody agreed to that definition
of correct: `major` would win over `critical` because it happened to be valid,
not because anyone decided. The apply therefore takes the file as a whole or
not at all, and names every problem at once, so they can be fixed in one pass
(R15.4).

**Finding out who to ask.** Both candidates say `User`, and both are on the same
trace. The trace id leads to the trace view, where both expectations sit with
their times. A reviewer who signed their rationale can be found there. One who
did not has to be found by asking whoever reviews that queue. This is why the
guide asks reviewers to sign a rationale when it matters who said it.

**Why `--verified-by` is required, and checked first.** The recorded author of
every candidate here is `User`, which names no one. A gold answer must name a
person who can be asked about it (R7.7). The check comes before any file is read
because a missing name is wrong whatever the files say: the refusal costs nothing
and leaves nothing half-done (R15.4 row 9).

---

## Task 8 — the maintainer's edit, and the signature

The three lines deleted from `candidates.jsonl`, leaving `major`:

```
$ git diff --stat
 review/incident-audit/candidates.jsonl | 3 ---
 1 file changed, 3 deletions(-)

$ dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks
  PLAY-1002.md  severity  'minor' -> 'major'
1 answer applied to gold/incidents, signed by a.aleks

$ git diff gold
--- a/gold/incidents/PLAY-1002.json
+++ b/gold/incidents/PLAY-1002.json
@@ -11,7 +11,11 @@
       "value": "2026-03-19"
     },
     "severity": {
-      "value": "minor"
+      "value": "major",
+      "verified_by": "a.aleks",
+      "verified_at": "2026-09-25",
+      "reason": "expected by User on 2026-09-25 in MLflow trace tr-3d54626f09316c030dfcea0bb07b6de1",
+      "superseded": "minor"
     },
     "affected_systems": {
       "value": "reporting-export"

$ dossier eval incident-audit --gold gold/incidents
5 documents · 5 fields · overall 84.0%
  loss_amount         60.0%   <- weakest
    PLAY-1001.md   ungrounded: the value may be right, and nothing in the document shows it
    PLAY-1003.md   ungrounded: the value may be right, and nothing in the document shows it
  resolution_date    100.0%
  severity            80.0%
    PLAY-1002.md   'minor' does not match 'major'
  affected_systems   100.0%
  root_cause          80.0%   (3 judged)
    PLAY-1003.md   root_cause: has a value and no source. A figure without evidence is the thing this system exists not to produce (R6.6).
recorded to MLflow: dossier-audit/incident-audit/eval

$ dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks
nothing to apply: every candidate is already gold
```

The stub's log still held 28 lines after the eval: no model call. Every judged
value had been judged before (R7.18).

**Who signed.** `a.aleks` signed, on the day of the apply. `s.brunner` appears
nowhere by name. The page recorded them as `User`, and the `reason` says exactly
that, with the trace their verdict is on — the way back to what they said and why.
The old value is kept as `superseded`, so the change can be reviewed as a change
and undone as one (R15.4 row 2, R7.7).

**What moved the score.** The run, the answers and the cache are all the same,
and `severity` went from 100% to 80%: the definition of correct changed, not the
answers. The pull's report is where getting that point back starts. `severity  0
yes · 1 no`, with its reason, says the prompt copies the label the note gives an
incident, where the organisation rates it by its SLA. That is a prompt change,
measured by the next eval (spec 015, Purpose).

```
$ git add gold review && git commit -qm "PLAY-1002 severity: major, from review"
$ dossier review pull incident-audit
…
$ git diff --stat
 review/incident-audit/candidates.jsonl | 3 +++
 1 file changed, 3 insertions(+)
```

**The lines come back, and that is right.** The pull mirrors the server, and the
three expectations are still on it. A line deleted from `candidates.jsonl` is a
decision about one apply: the file as the maintainer left it (R15.4 row 8). A
rejection that lasts is made where the verdict was left, by deleting it there.

```
$ python leave_verdicts.py http://127.0.0.1:5114 --reject
deleted  PLAY-1002.md  expectation severity     'critical'      tr-3d54626f09316c030dfcea0bb07b6de1
deleted  PLAY-1002.md  expectation summary      'The nightly e… tr-3d54626f09316c030dfcea0bb07b6de1
deleted  PLAY-1003.md  expectation severity     'catastrophic'  tr-fa197ad25569fb92ea73a2d7d82429c6

$ dossier review pull incident-audit
incident-audit  4 verdicts on 1 run
  extract  loss_amount  1 yes · 0 no
  extract  overall  1 yes · 0 no
  extract  severity  0 yes · 1 no · 1 value expected
      PLAY-1002.md  User: Two dashboards a day stale for a business morning is a missed reporting window, which the reporting SLA rates major, not minor.
written to review/incident-audit/feedback.jsonl
1 expected value written as gold candidates to review/incident-audit/candidates.jsonl

$ git diff --stat
 review/incident-audit/feedback.jsonl | 3 ---
 1 file changed, 3 deletions(-)

$ dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks
nothing to apply: every candidate is already gold
```

`feedback.jsonl` loses three lines because it holds every verdict, expectations
included. `candidates.jsonl` is back to the one line committed with the gold
change, so git sees no difference in it.

---

## Task 9 — nothing else reads a verdict, and a server nobody can review

```
$ git add review && git commit -qm "review: rejected for good"
$ dossier run incident-audit
run 20260925T103724Z-5e23 · …/runs/20260925T103724Z-5e23/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260925T103724Z-5e23
  extract: 5 document(s) · 5 from cache · 0 failed · 3 finding(s)
    PLAY-1001.md  loss_amount: span not found in PLAY-1001.md (R6.4).
    PLAY-1003.md  loss_amount: span not found in PLAY-1003.md (R6.4).
    PLAY-1003.md  root_cause: has a value and no source. A figure without evidence is the thing this system exists not to produce (R6.6).

$ DOSSIER_MLFLOW_CAPTURE=hashes dossier run incident-audit
run 20260925T103730Z-3253 · …/runs/20260925T103730Z-3253/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260925T103730Z-3253
  extract: 5 document(s) · 5 from cache · 0 failed · 3 finding(s)
    PLAY-1001.md  loss_amount: span not found in PLAY-1001.md (R6.4).
    PLAY-1003.md  loss_amount: span not found in PLAY-1003.md (R6.4).
    PLAY-1003.md  root_cause: has a value and no source. A figure without evidence is the thing this system exists not to produce (R6.6).

$ diff -r runs/20260925T103248Z-ee27/extract runs/20260925T103724Z-5e23/extract
$ diff -r runs/20260925T103248Z-ee27/extract runs/20260925T103730Z-3253/extract
$ diff runs/20260925T103248Z-ee27/manifest.json runs/20260925T103730Z-3253/manifest.json
2,3c2,3
<   "run_id": "20260925T103248Z-ee27",
<   "started_at": "2026-09-25T10:32:48.498948Z",
---
>   "run_id": "20260925T103730Z-3253",
>   "started_at": "2026-09-25T10:37:30.173575Z",
```

The stub's log: still 28 lines. The queue, `` tags.`dossier.review` = 'needed' ``:
six traces, `PLAY-1001.md` and `PLAY-1003.md` from each of the three runs.

`extract · PLAY-1002.md`, from each run:

```
run A  Request   {"document": "PLAY-1002.md", "inputs": {"documents": "<document key=\"PLAY-1002.md\"># PLAY-1002 — Nightly export missed the reporting window …
       Response  {"document": "PLAY-1002.md", "fields": [{"field": "loss_amount", "value": null, …
       severity  feedback false · expectation 'major'   (User)
run B  Request   {"document": "PLAY-1002.md", "inputs": {"documents": "<document key=\"PLAY-1002.md\"># PLAY-1002 — Nightly export missed the reporting window …
       Response  {"document": "PLAY-1002.md", "fields": [{"field": "loss_amount", "value": null, …
run C  Request   {"document": "PLAY-1002.md", "inputs": {"documents": "f318dcef630c1cb7c78377e51157756c4b649131cbc707760c618241ae071007"}}
       Response  {"artifact": "8963110e90d807aeebe5bb89df3244ed86d2552017baf3348cb1fdaf6818de54"}
```

**Run B has the same Request and Response and none of the verdicts.** Every run
opens traces of its own, and a cached answer is still an answer to review, so it
shows the same thing (R15.1 row 3). The verdicts stay where they were left, on
run A's trace. The next pull reads every trace in the run experiment, so it
still finds them: `incident-audit  4 verdicts on 1 run`, and `git status` clean.

**Clearing run A's tag leaves run B's alone.** With `dossier.review` cleared on
run A's `PLAY-1001` trace, the queue holds five: run B's and run C's
`PLAY-1001` traces are still tagged. That is right. Clearing a tag records that a
reviewer is done with one trace. Nothing about the answer changed, and run B
found the same ungrounded quote in the same cached answer. A doubt goes away when
the answer changes, not when someone reads it (R15.2 row 4).

**Run C holds nothing a reviewer can judge.** Its Request is the key and the
document's sha256, and its Response is the artifact's sha256. Someone with the
workspace can check those hashes: the snapshot store and `runs/` hold the bytes
they hash. A reviewer with only a browser cannot. `dossier` does not switch to
`full` for the runs a reviewer needs, because whether a server may hold the text
of your documents is a decision about that server, made by whoever runs it. A run
that overrode it because review wanted text would send documents where someone
had decided they must not go (R15.1 row 6, R10.8).

**What a verdict could have changed, and why it did not** (R15.5):

- **A key.** A key is a function of snapshots, prompts, schemas and the model
  identifier. No verdict is read on the run path, so none can enter one. Runs B
  and C were served entirely from cache.
- **The manifest.** Run C's differs from run A's in its run id and start time
  only. The capture setting is not in it, and no verdict is.
- **An artifact.** Both `diff -r` checks are empty, byte for byte.
- **A score.** `dossier eval` reads the gold set. A verdict reaches gold only when
  a maintainer applies it under their own name, and the one score that moved in
  this exercise moved at exactly that point, in task 8.

The fence is structural: only `dossier review pull` can build a `ReviewSource`,
and no run, plan, replay, eval or calibration imports anything that names a
verdict (`tests/architecture/test_R015_5__only_review_pull_reads_a_verdict.py`).

---

## What this exercise was really about

Two of its claims were wrong in the first draft, and the running made them right.

1. **Edit.** The draft had `j.okafor` press **Edit** on `s.brunner`'s thumbs-down
   to override it, as spec 015's table then said the page would. The page's
   JavaScript says otherwise: Edit is offered only on `User` verdicts, and is a
   `PATCH` in place. A verdict under a real name cannot be edited in the page at
   all, and an override is the API's. The spec's table and the reviewer guide
   were corrected first, and then this exercise.
2. **The server.** The first server's artifact root was built from Git Bash's
   `$PWD`, a POSIX path that MLflow on Windows read as a network share. It failed
   on every artifact it was sent, and the first command that sent one hung. The
   README's command is right on Linux and macOS. On Windows, build the path from
   `$(pwd -W)`.

The rest is what spec 015 promised, observed from the outside. A run shows a
reviewer the document and the answer, and points at what it doubts. People who
never run `dossier` leave verdicts in a browser. One command brings them back as
files `git` can diff. A reviewer's value reaches a score only through a
maintainer's signature. And nothing on the server moved a key, a manifest, an
artifact or a score.

**Back to:** [the playground index](../README.md).
