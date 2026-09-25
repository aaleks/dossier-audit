# 12 · Solution

Every command below was run against this repository, against a real MLflow 3.15.1
server with a SQLite backend. The output shown is the output it produced.

## Run the prepared answer

Terminal 1 — MLflow, with a database:

```bash
mkdir -p playground/work/12
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/12/mlflow.db \
  --artifacts-destination file://$PWD/playground/work/12/mlartifacts \
  --host 127.0.0.1 --port 5000
```

Terminal 2 — the stub model, with exercise 07's rules:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/07-calibrating-a-judge/resources/replies-judge.json \
  --replies playground/07-calibrating-a-judge/resources/replies.json \
  --port 8099
```

Terminal 3 — exercise 07's workspace (its gold set, judge rubric, sample and bar
are what this exercise publishes and scores), plus the `.env` from the README.
`solution/workspace/` holds the finished configuration, including the prompt with
task 5's line already in it and an `.env.example` of the four variables; copy it in
if you would rather not type. Then:

```bash
dossier sync incident-audit
dossier run incident-audit          # this is run A
dossier calibrate incident-audit --gold gold/incidents
```

```
incidents-manual  0 known · 0 changed · 5 new -> 5 fetched
ledger updated · 5 new snapshots · 0 tombstoned
run 20260922T055408Z-2071 · …/runs/20260922T055408Z-2071/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260922T055408Z-2071
  extract: 5 document(s) · 0 from cache · 0 failed
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8
recorded to MLflow: dossier-audit/incident-audit/calibrate
```

---

## Task 1 — publish the gold set, and read it back

```
incidents · 5 records · digest 2fa4b927
published to MLflow: dossier-audit/incident-audit/eval/incidents (d-199062269f9b4e428a0f7260df6e231f)
```

The dataset on the server, read back with `mlflow.genai.datasets.get_dataset`:

```
tags    dossier.gold_hash      8a13aeeeb0ff8f30677d8feb284a9f215de7e59822276761fef7b3cca36c4145
        dossier.snapshots_hash 4e100b0fcb16b22c6c550f8d1ba28f99b383592bccb643b18ccbebc0376cc6f3
        dossier.verified_by    a.aleks
records 5
  PLAY-1001.md  {"loss_amount": 18400.0, "resolution_date": "2026-03-04", "severity": "major", …}
  PLAY-1002.md  {"loss_amount": null,    "resolution_date": "2026-03-19", "severity": "minor", …}
  PLAY-1003.md  {"loss_amount": 61250.0, "resolution_date": "2026-04-07", "severity": "critical", …}
  PLAY-1004.md  {"loss_amount": 9900.0,  "resolution_date": "2026-05-12", "severity": "major", …}
  PLAY-1005.md  {"loss_amount": 2750.0,  "resolution_date": "2026-06-24", "severity": "major", …}
```

(The `gold_hash` above is the value the set ends on, after task 3's last publish.
At this point in the exercise it is the original set's hash — the tag is overwritten
by each publish, so the earlier values survive only on the runs that linked them.)

**What is in `inputs`, and what is not.** The document key, and nothing else:

```json
{
  "inputs": {"document": "PLAY-1001.md"},
  "expectations": {"loss_amount": 18400.0, "…": "…"},
  "tags": {"dossier.snapshot": "6bdb8cad3ebd2dcf76a24acdf1d36b55a5cda49f0a7222c9809044573892b1d0"}
}
```

The snapshot address cannot live in `inputs` because MLflow merges a record onto
`sha256(json.dumps(inputs, sort_keys=True))` — whatever is in there *is* the
record's identity. Put the snapshot beside the key and the first sync that repoints
a document (R2.18) would merge onto nothing: `PLAY-1001.md` would appear twice, once
addressing content the store no longer serves, and R12.3's claim that the document
is the merge key would be false. As a tag it is updated in place instead.

It also means you can publish a gold set before syncing anything. A document with
no ledger row simply gets no `dossier.snapshot` tag (R12.2 row 3).

**`PLAY-1002`'s `loss_amount` is `null`.** A reviewer read the note, saw that it
records no financial loss, and wrote that down. A field *absent* from
`expectations` means nobody verified it, and R7.3 row 4 keeps those two apart
throughout `dossier`: an unverified field is scored by nobody, and a verified `null`
is scored against a run that abstains. Dropping the null would turn the second into
the first, in the one artifact a person is most likely to read the gold set from.

**Which tag is not about the answers.** `dossier.snapshots_hash` — it is over the
document keys and the snapshot addresses they are held at, so it moves when a sync
repoints a document even though every answer is untouched. It exists so that a
publish can tell "nothing to send" from "the snapshot tags are wrong now"
(R12.3 row 4). `verified_by` is attribution for the set; `gold_hash` is the answers.

## Task 2 — publish it again, and watch nothing happen

```
incidents · 5 records · digest 2fa4b927
published to MLflow: dossier-audit/incident-audit/eval/incidents (d-199062269f9b4e428a0f7260df6e231f)
```

**Why the digest did not move.** Because nothing was sent. MLflow's digest is
`sha256("<name>:<last_update_time>")` — `_compute_dataset_digest` in
`sqlalchemy_store.py` — so it is a marker for *a write*, not a hash of the records:
merging the same five records again would have moved it. So a publish first asks the
registry what is there, compares the two hashes it would tag with the two already
on the dataset, and when they agree writes nothing at all — no records, no tags
(R12.3 row 1).

This is worth dwelling on because the implementation was wrong here first, and the
test suite agreed with it: `FakeDataset` computed its digest *from the records*, so
"republishing changes nothing" passed against a property MLflow does not have. A
live publish moved the digest on the second call. The fake's digest is now a
function of how many times it was written to, as the real one is.

After correcting `PLAY-1003`:

```
incidents · 5 records · digest 3043d4a8
```

**Which tag changed, and why the count did not.** `dossier.gold_hash`, because a
file's bytes changed. Five records still, because the merge key is the document and
`PLAY-1003.md` already had a record — the correction updated it in place. A record
keyed on the answer would have left the document holding two.

**What a person would have seen otherwise.** Two dataset versions with different
digests and identical contents, and no way to tell from the outside which pairs of
versions are worth diffing. The digest is the only handle MLflow gives you on "did
this change", and spending it on writes that changed nothing makes it useless.

## Task 3 — the eval links what it scored against

```
5 documents · 5 fields · overall 96.0%
  loss_amount        100.0%
  resolution_date    100.0%
  severity            80.0%   <- weakest
    PLAY-1003.md   'critical' does not match 'major'
  affected_systems   100.0%
  root_cause         100.0%   (4 judged)
recorded to MLflow: dossier-audit/incident-audit/eval/incidents
```

The run on the server:

```
inputs   [('incidents', '3043d4a8')]
tags     dossier.kind      eval
         dossier.gold_hash 1cdc3ac9…
         dossier.run_id    20260922T055408Z-2071
metrics  accuracy/severity 80.0   accuracy/overall 96.0   …
```

The dataset's own `gold_hash` tag is `1cdc3ac9` too, and its digest is the
`3043d4a8` this run links: the two agree, which is why there is no stale tag.

`inputs` is the link (R11.7): the dataset, by name and digest, beside the figures.
Anyone opening this run can open the answers it was measured against without
knowing what a gold hash is.

After reverting `PLAY-1003` and **not** republishing:

```
dataset incidents is stale: published 1cdc3ac9, scored 8a13aeee
  run `dossier dataset publish` to refresh it
5 documents · 5 fields · overall 100.0%
```

That run, read back:

```
inputs   [('incidents', '3043d4a8')]
tags     dossier.kind          eval
         dossier.dataset_stale true
         dossier.gold_hash     8a13aeee…
metrics  accuracy/severity 100.0   accuracy/overall 100.0   …
```

Two hashes on one run, and they disagree: `dossier.gold_hash` is the set that was
**scored**, because that is what the figures are about, and the dataset it links is
still at `3043d4a8`, the version published before the revert.

**Which answer the number came from.** The files. The dataset still holds `major`
at this moment, and the score went back to 100% because the files say `critical`
again — which is what R12.4 promises: a dataset is written from `gold/` and read by
a person, and no score is ever computed from one. The run is tagged
`dossier.dataset_stale=true` so that the disagreement is visible where the figure
is, rather than being something you find out by opening the dataset.

**Refuse, republish, or link and say so.** Linking and saying so is the only one of
the three that does not put a tracking server in charge of a local score.

- *Refusing* would mean a server's contents can stop an eval that reads nothing but
  files and a cache. R10.6 says a lost record never changes a command's outcome, and
  a stale record is a lesser problem than a lost one.
- *Republishing* would have an eval quietly mutate shared state. Publishing is a
  reviewer's act — it says "these are the agreed answers now" — and an eval doing it
  as a side effect would make that claim on their behalf.
- *Linking and saying so* records what happened, keeps the figure honest about where
  it came from, and leaves the fix to the person who knows whether the edit was
  meant.

**Why `8a13aeee` is a third hash.** The gold hash is over the *bytes* of the files
(R0.7), and rewriting a JSON file does not reproduce its original formatting —
indentation, key order, the trailing newline. The answers are the ones you started
with; the bytes are not. That is R12.3 row 5 exactly: a file rewritten with the same
answers formatted differently is sent, because the set the dataset claims to address
has moved. Publishing again gives a fourth digest for a set whose answers never
really changed:

```
incidents · 5 records · digest 70c68d1a
```

Whether that is right depends on what you think a gold set *is*. `dossier` takes it
to be the files, because the files are what is reviewed and what is in git — so two
sets that differ only in whitespace are two sets, and the cheap way to keep one hash
is not to rewrite the file.

## Task 4 — three ways to be told no

```
incident-audit: publishing a dataset needs tracking on: set DOSSIER_MLFLOW_ENABLED=true
and DOSSIER_MLFLOW_TRACKING_URI. A dataset is published to MLflow and nowhere else

incident-audit: no gold set at gold/incident

incident-audit: the MLflow server at http://127.0.0.1:5001 cannot hold an evaluation
dataset: /api/3.0/mlflow/datasets/search answered 500 Internal Server Error. Datasets
need a SQL backend -- start the server with --backend-store-uri (postgresql, mysql,
sqlite or mssql), not a file store.
```

**Why `publish` refuses where `run` does not.** Because the record *is* this
command's output. `dossier run` produces artifacts, a manifest and a report whether
or not anything is recording, so tracking off is a reduction in what you can inspect
later and not a failure. `dossier dataset publish` with tracking off has done
nothing at all, and exiting 0 would say otherwise (R12.5 row 1).

**The asymmetry with `eval`.** Against the same file-backed server:

```
dataset not linked: MLflow could not be asked for it
5 documents · 5 fields · overall 100.0%
  …
recorded to MLflow: dossier-audit/incident-audit/eval/incidents
```

An eval needs no dataset. It scores from the files and the cache, so a server that
cannot hold a dataset costs it one line of its record and nothing else (R12.5 row 5,
R10.6). A publish needs one by definition. The same server is fatal to one command
and irrelevant to the other, and that difference is the rule.

**A file store answers 500, not 404.** The route exists; the handler fails inside
it. `dossier` refuses on any answer that is not a success for exactly this reason —
when the check looked for `404` alone, this publish went through and MLflow's client
retried the 500 with backoff until the command appeared to hang. That was found by
running this exercise, not by the test suite, whose fake answered the 404 the code
expected. `MLFLOW_ALLOW_FILE_STORE=true` was needed to start the server at all:
MLflow 3.15 puts the file store in maintenance mode, which is the same fact said by
MLflow instead of by `dossier`.

## Task 5 — two runs, and the figure that hides a regression

```
run 20260922T055516Z-d3cf · …/runs/20260922T055516Z-d3cf/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260922T055516Z-d3cf
  extract: 5 document(s) · 0 from cache · 0 failed · 1 finding(s)
    PLAY-1002.md  loss_amount: has a value and no source. A figure without evidence
                  is the thing this system exists not to produce (R6.6).
```

**Why it asked the model again.** `0 from cache`. The *rendered* prompt is not in
the stage key — it holds the document and would change with every document — but the
prompt **template** is (spec 005). Editing `01_extract.md` moved the key for all
five documents, so run B is a different configuration rather than the same one
served from the cache. That is also why the v2 rules can match on a line only the
new prompt contains: run A and run B really are two different questions.

Note what the finding is. The v2 rules answer `loss_amount: 0.0` for `PLAY-1002`
with no `source`, and the run says so before anything is scored: a figure without
evidence is caught on the way out, not at scoring time (R6.6).

## Task 6 — read the change gate in MLflow

```
compare 20260922T055408Z-2071 -> 20260922T055516Z-d3cf · 5 documents · overall 100.0% -> 92.0% (-8.0)
  loss_amount        100.0%  80.0%  -20.0   <- regression
  resolution_date    100.0%  80.0%  -20.0   <- regression
  severity           100.0% 100.0%   +0.0
  affected_systems   100.0% 100.0%   +0.0
  root_cause         100.0% 100.0%   +0.0
recorded to MLflow: dossier-audit/incident-audit/compare/incidents
```

The run:

```
metrics  a/loss_amount 100.0   b/loss_amount 80.0   delta/loss_amount -20.0
         a/resolution_date 100.0   b/resolution_date 80.0   delta/resolution_date -20.0
         a/severity 100.0   b/severity 100.0   delta/severity 0.0
         a/affected_systems 100.0  b/affected_systems 100.0  delta/affected_systems 0.0
         a/root_cause 100.0   b/root_cause 100.0   delta/root_cause 0.0
         a/overall 100.0   b/overall 92.0   delta/overall -8.0
tags     dossier.kind      compare
         dossier.regressed loss_amount, resolution_date
         dossier.gold_hash 8a13aeee…
params   a 20260922T055408Z-2071   a/model openai:gpt-5.4-mini
         b 20260922T055516Z-d3cf   b/model openai:gpt-5.4-mini
inputs   [('incidents', '70c68d1a')]
```

**Why record both sides.** A delta of `-20.0` says something moved and not what it
moved *from*. `80.0` after `100.0` is a field that broke; `80.0` after `82.0` is
noise. Without `a/` and `b/` you would open two more runs to tell those apart — and
the whole reason this rule exists is that opening things later is what people do not
do. Recording three numbers where the report prints three columns also keeps spec
011's promise: MLflow is a second place to read a figure, never a second way of
arriving at one.

**The filter.** `tags.\`dossier.regressed\` LIKE '%affected_systems%'` finds every
comparison in which that field got worse. That is the query the tag exists for: the
question is never "show me comparisons", it is "when did this field break".

An *absent* tag on a clean comparison would break it. You could not tell a
comparison where nothing regressed from one recorded before the tag existed, which
is the same reasoning that has `sync` attach a `changes.json` holding two empty
lists rather than no artifact (R11.6 row 2). So it is present and empty.

**Why `compare/` and not beside the evals.** Put `accuracy/severity` and
`delta/severity` in one experiment and MLflow shows you a column of numbers where
`100.0` means "all correct" in some rows and "improved by a hundred points" in
others. An experiment should hold runs that are comparable with one another (R10.2),
and an accuracy and a delta are not.

**The two regressions are not the same kind of wrong.** `resolution_date` is
`04.03.2026`, which is the 4th of March in one country and the 3rd of April in
another: it is refused as *unreadable* rather than scored as a disagreement, because
those want different work (R7.1). `loss_amount` is `0.0` with no span, so it is
*ungrounded* — the finding run B already printed (R6.6). Both count as not-correct
and the comparison does not distinguish them, deliberately: a delta answers "did
this get worse", and `dossier eval` on run B answers "how". Two questions, two
commands, and the second one is one line away.

---

## What this exercise was really about

Three of the bugs fixed while spec 012 was being built were found exactly this way —
by running the commands against a real server rather than against a fake:

1. the digest that moved on a republish that changed nothing, because MLflow's is
   over a timestamp and the fake's was over the records;
2. `log_inputs` raising `TypeError` when handed an `EvaluationDataset`, because it
   wants a `DatasetInput`;
3. the file-backed server answering 500 where the check looked for 404, which turned
   a refusal into a hang.

Every one of them had a green test suite over it. A fake is a claim about somebody
else's system, and the only way to find out whether the claim is true is to make the
call.

**Back to:** [the playground index](../README.md).
