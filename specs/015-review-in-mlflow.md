# 015 — Review in MLflow

**Status:** Implemented
**Rules:** R15.1 – R15.6

## Purpose

The people who can say whether an answer is right are rarely the people who run
`dossier`. A daily run over new Jira issues is recorded to MLflow already (spec
011); this spec makes that record the place those people review it. They open a
trace, read the issue and the answer side by side, and leave a verdict -- a
thumbs-down with a reason, or the value that should have been there. `dossier`
reads those verdicts back through one command, and they become two things: a
report of what reviewers disagreed with, step by step and field by field, which
is where prompt work starts; and gold candidates, which a maintainer applies to
the gold set as a reviewed change (R7.7).

Without it, a reviewer's knowledge reaches the gold set only if they learn the
CLI, and a wrong answer that someone noticed is noticed once and lost.

## The flow

```
cron (daily)   dossier sync incident-audit && dossier run incident-audit --label daily
                   │  new issues only; the rest is served from cache (R2.1, R5.5)
                   ▼
MLflow         one trace per (step, document): the document it read as its request,
                   │  the answer as its response (R15.1); traces the run itself
                   │  doubts tagged dossier.review = needed (R15.2)
                   ▼
reviewers      the trace list, filtered on that tag or on a thumbs-down; feedback
                   │  (yes/no, a reason) and expectations (the right value), each
                   │  carrying who left it -- as many reviewers at once as the server holds
                   ▼
dossier        dossier review pull incident-audit      -> review/incident-audit/
                   │    feedback.jsonl    every human verdict, with who, when and where
                   │    candidates.jsonl  every expected value, as a gold candidate
                   │  (R15.3, R15.4); the only command that reads a verdict back (R15.5)
                   ▼
maintainer     reads the diff, deletes what they reject, then signs what is left:
               dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks
```

## What open-source MLflow offers, and what it does not

Checked against MLflow 3.15.1 before these rules were written -- the API live,
against a server, and the web UI in the JavaScript it ships:

| Capability | Open-source MLflow | Used here |
|---|---|---|
| A trace's inputs and outputs shown as the trace list's Request and Response columns | yes | R15.1 |
| A trace list filtered on a tag: `` tags.`dossier.review` = 'needed' `` | yes, and the filter is kept in the URL, so a queue is a link | the queue (R15.2) |
| A trace list filtered on a verdict: `` feedback.`severity` = 'false' ``, `` expectation.`severity` `` | yes | a second queue, for what reviewers disagreed with |
| Adding feedback (a boolean, number or string, with a rationale) and expectations (the same, or JSON) from a trace | yes | R15.3, R15.4 |
| Editing a verdict from the trace view | only one whose author is `User` -- the page's own user, and so every verdict left through it -- and in place: the same id, with no record of the value it replaced or of who replaced it. A verdict under any other name shows no Edit | a committed `feedback.jsonl` is the history the server does not keep (R15.3) |
| Overriding a verdict: a new one naming it, the old one marked invalid | from the trace view, only feedback no person left, such as a judge's; any verdict through the API (`mlflow.override_feedback`) | only valid verdicts are read (R15.3) |
| Deleting a verdict from the trace view | yes, whoever left it | a candidate is rejected for good where it was left |
| Editing a trace's tags from the trace list | yes | a reviewer may clear `dossier.review` once done |
| **Who left a verdict** | the trace view records **`User`**, a fixed string, whoever is logged in | reported as recorded, never guessed; gold is signed by the maintainer who applies it (R15.4) |
| Labeling sessions and the Review App, MLflow's assigned queues that record the logged-in user | **Databricks only**: `Supported URI schemes are: ['databricks']` | not used |

So the queue is a filter anyone can open, not an assignment. Every reviewer sees
the same traces and the same verdicts, and parallel review needs nothing more
than a shared server.

The author row decides a rule. A verdict left in open-source MLflow's trace view
does not say who left it: the UI sends `source_id: "User"` for everyone, and the
server stores what it is sent. A verdict logged through the API, or by a server
that records its users, carries a real name, and `dossier` reports whichever it
finds. Neither is a signature a gold set can rest on (R7.7), so an expected value
enters gold under the name of the maintainer who applied it, with the trace and
the recorded author kept in its reason.

The same fixed string decides what Edit does. The page compares a verdict's
author with its own user, which is always `User`: a verdict left through the page
is everyone's to edit, and an edit replaces it where it stands, so the server
keeps no earlier value and no name for the change. An override -- the new verdict
naming the old, which R15.3 reads in its place -- comes from the API, or from the
page on a judge's feedback. Corrected after the rules were written, from the
page's JavaScript and a live edit, which kept the verdict's id and wrote no
override.

## Names a reviewer uses

A verdict is named after what it is about, typed into MLflow's "Add feedback" or
"Add expectation" form. **A field's name** -- `loss_amount`,
`root_cause` -- for a verdict about one field, which is the only kind that can
become a gold candidate. **Anything else** -- `overall`, `summary` -- for a
verdict about the whole answer, which the report counts and gold never sees.

| On the trace of `extract · INC-4822` | Becomes |
|---|---|
| feedback `severity` = no, reason "payments stopped for an hour: major, not minor" | a thumbs-down on `extract`'s `severity` in the report |
| expectation `severity` = `major` | a gold candidate for `INC-4822`'s `severity` |
| feedback `overall` = yes | a thumbs-up on `extract` in the report |

## Must hold

### R15.1 — a run's trace shows the document it read as its request and the answer it gave as its response

The trace list is the first thing a reviewer sees, and its request and response
columns were empty on every trace `dossier` wrote: the document was in an LLM
span's prompt, the answer in its reply, both two clicks down and neither
labelled. The trace now carries them where MLflow shows them.

The request is the document key, and beside it each value the step was handed,
under the input's name -- `documents`, `extract` -- as the prompt was rendered
with them (R3.13). The values sit under `inputs` of their own, so a step that
happens to be called `document` cannot stand in for the key. The response is the answer as `runs/` holds it (R0.11): the field
record, parsed, for a step with an output; the prose, for one without. A
document served from cache shows the answer it was served, and one that failed
shows the error it failed with.

Under `DOSSIER_MLFLOW_CAPTURE=hashes` neither holds a word of the document or the
answer, as no span does (R10.8): the request is the key and each value's hash,
and the response the artifact's hash. Review in MLflow needs `full`; that is a
decision about the server, and it is the person running it who makes it.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`), infrastructure (`dossier.infrastructure.tracking.mlflow`)
- **Proved by:** `tests/unit/test_R015_1__a_trace_shows_the_document_and_the_answer.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract · INC-4821`, nothing cached, capture `full` | request `{"document": "INC-4821", "inputs": {"documents": "<document key=\"INC-4821\">…"}}`; response the field record `extract/INC-4821.json` holds, as JSON |
| 2 | `verify · INC-4821`, reading `[documents, extract]` | the request's `inputs` holds both values under their names |
| 3 | the same run again, `extract` served from cache | the same request and the same response: a cached answer is still an answer to review |
| 4 | `INC-4822` failing validation twice (R6.2) | the response is `{"error": …}`, the error the trace already carries (R11.1 row 4) |
| 5 | a step with no `output`, `report` in `aggregate` mode | the response is the report's prose |
| 6 | *counter-example* — capture `hashes` | the request is `{"document": "INC-4821", "inputs": {"documents": "<sha256>"}}` and the response `{"artifact": "<sha256>"}`; no text of either (R10.8) |

### R15.2 — a run tags the trace of every document it doubts, and names the fields it doubts

A reviewer's time goes furthest on the answers `dossier` itself was not sure of.
A run already knows which those are: a document that failed, and a field that
is ungrounded or invalid (R6.16). Each such trace is tagged
`dossier.review = needed`, and `dossier.findings` names each field and why, so the
queue is one filter -- `` tags.`dossier.review` = 'needed' `` -- and the reason is
on the row.

A trace with nothing doubtful carries neither tag. It can still be reviewed --
the filter is where to start, not a fence -- and a thumbs-down on a trace the run
was sure of is the most useful verdict there is.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R015_2__a_run_tags_what_it_doubts.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract · INC-4822` with `loss_amount` ungrounded (R6.4) | tags `dossier.review` `needed` and `dossier.findings` `loss_amount: ungrounded` |
| 2 | `INC-4822` failing validation twice | `dossier.review` `needed`, `dossier.findings` `failed` |
| 3 | two fields in doubt, `root_cause` invalid and `loss_amount` ungrounded | `dossier.findings` `loss_amount: ungrounded; root_cause: invalid`, sorted by field |
| 4 | the same run again, served from cache | the same tags: a doubt does not go away because the answer was cached |
| 5 | *counter-example* — `INC-4821`, every field grounded or abstaining | neither tag |
| 6 | *counter-example* — a field `described` from a picture (R6.15) | not a doubt; the judge decides it (R7.21), and it is not tagged |

### R15.3 — `dossier review pull` writes every valid human verdict on a pipeline's runs, and reports them by step and name

One command reads the verdicts back: `dossier review pull <pipeline>`. It reads
the traces of the pipeline's run experiment (R10.2) and keeps the assessments a
person left -- source `HUMAN` -- that are still valid, so a verdict another
reviewer overrode is read as the override. The judge's verdicts (R11.16) are the
judge's, not a reviewer's, and are left where they are.

It writes `review/<pipeline>/feedback.jsonl`, one line per verdict: the run id,
step and document the trace is about, the verdict's name, kind and value, the
reason, who left it and when, and the trace and assessment ids that lead back to
it. The file is the whole set each time, sorted, so a second pull with nothing
new rewrites the same bytes and `git diff` shows exactly what reviewers added.
It prints the verdicts by step and name -- how many yes, how many no, and each
no with its document, reviewer and reason -- because that is where prompt work
starts.

It refuses before any work with tracking off, since its whole input is the
server, and with the server unreachable (R10.5).

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking.mlflow`), application (`dossier.application.review`), cli (`dossier.cli.review`)
- **Proved by:** `tests/unit/test_R015_3__review_pull_writes_every_human_verdict.py`, `tests/acceptance/test_R015_3__a_reviewers_verdicts_come_back.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | on run `20260806T142203Z-4f1a`'s `extract · INC-4822`, `s.brunner` left feedback `severity` = no, "payments stopped for an hour: major, not minor", in the trace view | one line naming that run, `extract`, `INC-4822`, `severity`, `feedback`, `false`, the reason, `User` -- as MLflow recorded the author -- and when; the report prints `extract  severity  0 yes · 1 no` and the reason beneath |
| 2 | `j.okafor` then overrode it with yes | the line is the override's yes; the no it replaced is not read |
| 3 | the judge's verdicts from an eval of that run (R11.16) | not read; they are not a reviewer's |
| 4 | the same pull again, nothing new on the server | `feedback.jsonl` byte-identical |
| 5 | feedback `overall` = yes on `verify · INC-4821`, logged through the API as `s.brunner` | a line naming `s.brunner`: the author MLflow holds is reported, whatever it is, and none is invented |
| 6 | *counter-example* — `DOSSIER_MLFLOW_ENABLED` unset | refused before any work, naming the variable; nothing written |
| 7 | *counter-example* — no human verdict on any of the pipeline's runs | `no reviewer verdicts on incident-audit's runs`, and no file written |
| 8 | `severity` = yes on `extract · INC-4821`, and row 1's no on `extract · INC-4822` | the report prints `extract  severity  1 yes · 1 no`, and beneath it the no's reason; a yes has none to print, and the reasons after it are still printed |

### R15.4 — a reviewer's expected value is a gold candidate, and becomes gold only when a maintainer applies it

An expectation says what the right value was. `dossier review pull` writes each
valid one to `review/<pipeline>/candidates.jsonl` as a candidate -- the document,
the field, the value, who said so and when, and the trace it was said on -- and
changes nothing in the gold set. A maintainer reads the file, deletes the lines
they reject, and runs `dossier review apply <pipeline> --gold <dir> --verified-by
<name>`, which passes each remaining candidate through `apply_correction` (R7.7).
The maintainer is `verified_by` and the day they applied it `verified_at`: the
author MLflow recorded is `User` for everyone who used the trace view, and a gold
answer is signed by a person who can be asked about it. The recorded author, the
trace and the reviewer's reason go into the entry's `reason`, and the value it
replaces is kept beside it as `superseded`. A document not yet in gold gets a
file of its own.

Nothing is applied if anything is wrong. A candidate naming a field the
pipeline's declaration does not have, a value an enum does not allow, or two
reviewers expecting different values for one field of one document refuses the
whole apply, naming each, before a file is written -- a gold set half-applied is
a definition of correct nobody agreed to.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.review`, `dossier.domain.gold`), application (`dossier.application.review`), cli (`dossier.cli.review`)
- **Proved by:** `tests/unit/test_R015_4__a_candidate_becomes_gold_when_applied.py`, `tests/acceptance/test_R015_4__a_maintainer_applies_what_reviewers_expected.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `s.brunner`'s expectation `severity` = `major` on `extract · INC-4822` | a candidate line in `candidates.jsonl` naming the document, field, value, the author `User`, the day and the trace; `gold/incidents/INC-4822.json` unchanged |
| 2 | `dossier review apply incident-audit --gold gold/incidents --verified-by a.aleks` | `INC-4822.json`'s `severity` is `major`, `verified_by` `a.aleks`, `verified_at` the day of the apply, `superseded` `minor`, and a `reason` naming the trace and `User` |
| 3 | an expectation `root_cause` for `INC-4830`, which has no gold file | `gold/incidents/INC-4830.json` written, holding that one field, signed by `a.aleks` |
| 4 | the same apply again | nothing changes: the value, the reviewer and the day are already there |
| 5 | *counter-example* — `s.brunner` expecting `major` and `j.okafor` `critical` for the same field of `INC-4822` | the apply refused, naming both; no gold file written |
| 6 | *counter-example* — an expectation named `summary`, which the declaration does not have | refused, naming it; a verdict about the whole answer is the report's, never gold's |
| 7 | *counter-example* — `severity` = `catastrophic`, not among `minor`, `major`, `critical` | refused, naming the allowed values |
| 8 | *counter-example* — the maintainer deleted a candidate's line before applying | that candidate is not applied: the file as the maintainer left it is the decision |
| 9 | *counter-example* — `dossier review apply` with no `--verified-by` | refused before any file is read; there is no anonymous path into the gold set (R7.7) |
| 10 | the maintainer deleted a candidate's line and left it blank, with row 1's candidate after it | row 1's candidate is applied. A blank line is not a candidate, and not the end of the file either |

### R15.5 — only `dossier review pull` reads a verdict back, and what it reads reaches the review files and nothing else

MLflow has been something `dossier` writes to and never an input (R0.10, R12.4,
R13.4, R14.5). Review makes one exception, and fences it the way each of those
did. Verdicts are read through a port of their own, `ReviewSource`, which only
`dossier review pull` builds; the `Tracker` still returns nothing (R0.10 row 5).
What it reads lands in `review/<pipeline>/`, which no command reads but `review
apply`, and reaches the gold set only through a file a maintainer applied with a
reviewer's name on every line (R7.7). No run, plan, replay, eval or calibration
reads a verdict, so a verdict left on the server changes no key, manifest,
artifact or score.

- **Kind:** deterministic
- **Layer:** architecture, application (`dossier.application.review`)
- **Proved by:** `tests/architecture/test_R015_5__only_review_pull_reads_a_verdict.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | every module of `dossier.cli` | `build_review_source` called from `review pull` and from no other command |
| 2 | the `Tracker` port | still declares no method returning anything read from the server (R0.10 row 5) |
| 3 | a run of `incident-audit` after reviewers left verdicts on the last one | the same keys, manifest and artifacts as with none; nothing was read |
| 4 | *counter-example* — `dossier eval` after a pull, with `candidates.jsonl` unapplied | scores against the gold set as it is; a candidate is not gold until applied |

### R15.6 — a `per_part` document's trace shows each page's answer under the page's name

R15.1 says a trace's response is the answer as `runs/` holds it. For a
`per_part` step, `runs/` holds one file per page:
`runs/<id>/extract/<document>/page-001.json` and so on (R3.12). The run instead
parsed the document's joined text as JSON. That text wraps each page in a
`<part>` tag for a later step to read, so it is not JSON. With MLflow on, every
`per_part` run stopped after its first document with
`Expecting value: line 1 column 1 (char 0)`. This was found live on 2026-09-29
and had been there since R15.1. R10.6 did not catch it, because the response is
built before the best-effort tracker receives it, so the failure was the run's.

The response is now an object with one key per page, each page's answer shown
as R15.1 shows a document's. The joined text is unchanged, because a later step
reads it and a reviewer does not.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.tracking.trace_pages`), application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R015_6__a_page_by_page_trace_shows_each_page.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract · INC-4830-postmortem-checkout-tls-expiry.pdf`, `per_part` over its three pages, capture `full` | response `{"page-001.png": …, "page-002.png": …, "page-003.png": …}`, each the field record that page's file under `runs/` holds, as JSON; the run completes |
| 2 | `INC-5720-checkout-latency-postmortem.png`, one page | `{"page-001.png": …}`: still keyed by its page, because `runs/` holds `page-001.json` and no file for the document as a whole |
| 3 | `INC-4830`'s page 2 failing validation twice (R6.2) | `{"error": …}`, as R15.1 row 4: the document failed, and its trace says so |
| 4 | capture `hashes` | `{"page-001.png": {"artifact": "<sha256>"}, …}`, each the hash of that page's file; no text of any answer (R10.8) |
| 5 | *counter-example* — `extract · INC-4821`, a `per_file` step | the field record itself, keyed by no page (R15.1 row 1) |
