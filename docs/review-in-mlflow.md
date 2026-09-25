# Review in MLflow

The people who can say whether an answer is right are rarely the people who run
`dossier`. This is how they review its answers in MLflow, where the runs already
are, and how what they say comes back: as a report for prompt work, and as gold
candidates a maintainer applies. Spec 015 is the contract; this is the tour.

```
cron (daily)   dossier sync incident-audit && dossier run incident-audit --label daily
                   ▼
MLflow         one trace per (step, document): the document as its Request,
                   │  the answer as its Response; doubtful ones tagged for review
                   ▼
reviewers      thumbs up or down, a reason, and the value that should have been there
                   ▼
maintainer     dossier review pull incident-audit        -> review/incident-audit/
               dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks
```

## Setting it up

Review happens on the MLflow server the runs record to, so tracking is on and
the server keeps the text a reviewer needs to read:

```bash
# .env on the machine that runs dossier
DOSSIER_MLFLOW_ENABLED=true
DOSSIER_MLFLOW_TRACKING_URI=https://mlflow.example.internal
DOSSIER_MLFLOW_CAPTURE=full        # the document and the answer on each trace
```

`DOSSIER_MLFLOW_CAPTURE=full` is the decision that matters. With `hashes`, a
trace holds hashes and no text (R10.8), which is right for a server that must
not see your documents -- and makes review in MLflow impossible, because there is
nothing on the trace to read. Decide it per server, knowing that.

The run itself is whatever you already schedule. A daily cron is enough:

```bash
0 6 * * *  cd /srv/audit && dossier sync incident-audit && dossier run incident-audit --label daily
```

New issues are fetched and asked about; everything else is served from cache and
costs nothing (R2.1, R5.5).

## For reviewers: what to do in MLflow

You never need `dossier`, only a browser and an account on the MLflow server.

**Open the queue.** In the run experiment (`dossier-audit/incident-audit/run`),
open *Traces* and filter on:

```
tags.`dossier.review` = 'needed'
```

Those are the answers `dossier` itself doubted -- a document it could not answer,
or a field whose evidence it could not find (`ungrounded`) or whose record was
malformed (`invalid`). The tag `dossier.findings` on each row says which field
and why, for example `loss_amount: ungrounded`. MLflow keeps the filter in the
page's address, so a queue is a link you can bookmark and share. The filter is
where to start, not a fence: any trace can be reviewed, and a thumbs-down on an
answer `dossier` was sure of is the most useful verdict there is.

**Read the trace.** Its *Request* is the document as the step read it; its
*Response* is the answer, field by field, with the passage each value was
taken from.

**Say what you think.** On the trace, *Add feedback* or *Add expectation*:

| You want to say | Use | Name | Value |
|---|---|---|---|
| one field is wrong | feedback | the field, e.g. `severity` | Boolean `false`, and a rationale saying why |
| one field is right | feedback | the field | Boolean `true` |
| what the value should have been | expectation | the field | the right value, e.g. `major` |
| the whole answer is good or bad | feedback | `overall` (or any name that is not a field) | Boolean, and a rationale |

Use the field's own name for anything about one field: only an expectation named
after a field can become a gold answer.

**Changing a verdict.** The page thinks everyone is `User`, so every verdict left
through it is yours to edit -- and everyone else's. An edit replaces the verdict
where it stands: MLflow keeps neither the value it replaced nor who replaced it.
A verdict logged under a real name, through the API, shows no Edit; it can be
deleted in the page, or overridden through the API (`mlflow.override_feedback`),
which leaves the old verdict in place, marked as overridden, and stops it
counting.

**Two things to know.**

- *Your name is not recorded.* Open-source MLflow's trace view records every
  verdict's author as `User`, whoever is logged in. If it matters who said it,
  sign the rationale. Gold is signed by the maintainer who applies it. And since
  anyone can edit a `User` verdict in place, the only history of what a verdict
  said is the maintainer's committed `feedback.jsonl`.
- *Assigned queues are not available.* MLflow's labeling sessions and Review App
  exist only on Databricks. Here everyone sees the same traces and the same
  verdicts, so agree among yourselves who takes which part of the queue.

## For maintainers: bringing the verdicts back

```bash
dossier review pull incident-audit
```

```
incident-audit  3 verdicts on 1 run
  extract  overall  0 yes · 1 no
      INC-4822  User: the loss figure is invented
  extract  severity  0 yes · 1 no · 1 value expected
      INC-4822  User: payments stopped for an hour: major, not minor
written to review/incident-audit/feedback.jsonl
1 expected value written as gold candidates to review/incident-audit/candidates.jsonl
```

It reads the pipeline's run experiment and writes two files under
`review/incident-audit/`:

- **`feedback.jsonl`** -- every verdict a person left and still stands by, one per
  line: which run, step and document, the name, the value, the reason, who
  (as MLflow recorded it) and when, and the trace it is on. The whole set each
  time, sorted, so a pull with nothing new changes no byte and `git diff` shows
  exactly what reviewers added. Commit it if you want the history. The report
  printed from it is where prompt work starts: a field with a run of
  thumbs-down, and their reasons, says what the prompt gets wrong.
- **`candidates.jsonl`** -- every expected value, as a gold candidate. Nothing in
  the gold set has changed.

Overridden verdicts are read as their override; the judge's own verdicts from
`dossier eval` are not a reviewer's and are left out. With tracking off the
command refuses: the verdicts are on the server and nowhere else.

**Decide, then sign.** Read `candidates.jsonl`. Delete the lines you reject, then:

```bash
dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks
```

```
  INC-4822  severity  'minor' -> 'major'
1 answer applied to gold/incidents, signed by a.aleks
```

Each candidate goes into the gold file through the same path as any correction
(R7.7): signed by you, dated today, with the value it replaced kept as
`superseded` and the trace and recorded author in its `reason`. A document with
no gold file gets one. Applying again changes nothing.

Nothing is applied if anything is wrong -- every problem is named, and no file is
written:

- a name the declaration has no field for (`summary`): a verdict about the whole
  answer belongs in the report, never in gold;
- a value an enum does not allow (`severity` `catastrophic`);
- two reviewers expecting different values for one field of one document --
  settle it, delete the line you reject, and apply again.

Without `--verified-by` the command refuses. There is no anonymous path into the
gold set, and MLflow's `User` is not a signature.

**Rejecting for good.** A pull rewrites `candidates.jsonl` from what is on the
server, so a line you deleted comes back on the next pull. To reject a candidate
for good, delete the expectation in MLflow, where it was left.

## What never happens

`dossier review pull` is the only command that reads anything back from MLflow
(R15.5). A run, `--plan`, `--replay`, `dossier eval` and `dossier calibrate` read
no verdict, so a verdict left on the server changes no cache key, manifest,
artifact or score. A reviewer's value reaches a score only after a maintainer
applied it to the gold set, under their own name, as a change you can review in
git.
