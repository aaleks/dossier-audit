# 13 · Solution

Every command below was run against this repository, in one pass from an empty
server, against a real MLflow 3.15.1 server with a SQLite backend. The output shown
is the output it produced, with four liberties taken in how it is shown: the
workspace's absolute path is shortened to `…` and written with `/`; MLflow's own
log lines (its `View run` links and the trace queue's flush notice) are left out,
being MLflow talking rather than `dossier`; `links.py` rows a checkpoint has already
shown are elided as `…` in task 6; and the byte-for-byte check at the end is shown
as the `diff -r` that made it.

## Run the prepared answer

Terminal 1 — MLflow, with a database of its own:

```bash
mkdir -p playground/work/13-server
.venv/bin/mlflow server \
  --backend-store-uri sqlite:///$PWD/playground/work/13-server/mlflow.db \
  --artifacts-destination file://$PWD/playground/work/13-server/mlartifacts \
  --host 127.0.0.1 --port 5113
```

Terminal 2 — the stub, with exercise 12's second-prompt override in front of
exercise 07's rules:

```bash
.venv/bin/python playground/toolkit/stub_model.py \
  --replies playground/12-a-dataset-and-the-change-gate/resources/replies-prompt-v2.json \
  --replies playground/07-calibrating-a-judge/resources/replies-judge.json \
  --replies playground/07-calibrating-a-judge/resources/replies.json \
  --port 8113 --log playground/work/13-server/calls.jsonl
```

Terminal 3 — exercise 07's material, with this exercise's `.env`:

```bash
W=playground/work/13
mkdir -p $W/inbox/incidents $W/gold/incidents/samples
cp -r playground/07-calibrating-a-judge/solution/workspace/. $W/
cp playground/corpus/incidents/PLAY-100[1-4].md $W/inbox/incidents/
cp playground/07-calibrating-a-judge/resources/documents/PLAY-1005.md $W/inbox/incidents/
cp playground/07-calibrating-a-judge/resources/verified-answers/*.json $W/gold/incidents/
cp playground/07-calibrating-a-judge/resources/calibration-sample/root_cause.jsonl \
   $W/gold/incidents/samples/
cp playground/07-calibrating-a-judge/resources/judge-threshold/judge.yaml \
   $W/gold/incidents/judge.yaml
cp playground/13-prompts-and-pipeline-versions-in-mlflow/solution/workspace/.env.example $W/.env

cd $W
dossier sync incident-audit
dossier run incident-audit          # this is run A
dossier calibrate incident-audit --gold gold/incidents
```

```
incidents-manual  0 known · 0 changed · 5 new -> 5 fetched
ledger updated · 5 new snapshots · 0 tombstoned

run 20260923T054607Z-7693 · …/runs/20260923T054607Z-7693/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260923T054607Z-7693
  extract: 5 document(s) · 0 from cache · 0 failed

root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
recorded to MLflow: dossier-audit/incident-audit/calibrate
```

`dossier` runs inside the workspace (`cd $W` above) and `links.py` from the
repository root, as the README shows; below, the latter is written
`python links.py`.

---

## Task 1 — publish the prompts, and read one back

```
$ dossier prompts publish incident-audit
incident-audit · 2 prompts
  incident-audit.extract           b3c909cf  v1  created
  incident-audit.judge.root_cause  0443845a  v1  created
2 versions created, 0 unchanged
published to MLflow: http://127.0.0.1:5113
```

```
$ python links.py
prompt   incident-audit.extract                     v1  b3c909cf
prompt   incident-audit.judge.root_cause            v1  0443845a
run      dossier-audit/incident-audit/calibrate         calibrate incidents · openai:gpt-5.4-mini                  -
run      dossier-audit/incident-audit/run               20260923T054607Z-7693                                      -
run      dossier-audit/incident-audit/sync              sync 20260923T054603Z                                      -
version  m-1ad03e5466074e599e82a85f1d4ec95e  -
```

Version 1 of `incident-audit.extract`, read back with
`MlflowClient.get_prompt_version`. This read is from an earlier pass of the same
exercise — the pass above ends by deleting every prompt — and every value in it is
a function of the prompt file alone, so it is the same in both:

```
template        Extract the requested fields from the incident note below.
                …  (the file's text, as it is on disk)
commit message  dossier: prompts/01_extract.md b3c909cf
tags            dossier.prompt_hash  b3c909cfe88ac27ee0ff7bd2f51cd7dc6961900e2607199bbfcf5186df57ba0a
                dossier.pipeline     incident-audit
                dossier.step         extract
                dossier.path         prompts/01_extract.md
```

The rubric's version carries `dossier.field: root_cause` where the prompt carries
`dossier.step`, and `dossier.path: rubrics/root_cause.md`.

**The dot.** The obvious spelling is `incident-audit/extract`, and it is not
available: MLflow's name validation refuses `/` and `:` in a prompt name. A step
id is held to `[a-z][a-z0-9_]*` and can hold neither; a pipeline's name is a
directory name and could hold `:` on some systems, which is why `dossier` refuses
both characters where it composes the name rather than letting MLflow refuse them
where it is sent (R14.1).

**The field, not the step.** A rubric belongs to a field declaration, and two
steps can declare one field — `extract` and a `verify` step both producing
`root_cause`, say. Named after a step, one rubric would publish twice, under two
names, and its version history would split in half. Named after the field, it is
one prompt with one history, because it is one job (R14.2).

**The full hash.** `b3c909cf` is already on run A's record, which was made before
anything was published — as the param `prompt/extract`, in all 64 characters
(R11.18). The tag on the prompt version is the same 64 characters, and it is the
only value that ties a version in the registry back to a run's provenance. Eight
characters are enough for a person to recognise a hash in a terminal and not
enough to be unique; a prefix would tie one version to several prompts (R14.3,
R0.7).

---

## Task 2 — publish it again, twice, and then run

```
$ dossier prompts publish incident-audit
incident-audit · 2 prompts
  incident-audit.extract           b3c909cf  v1  unchanged
  incident-audit.judge.root_cause  0443845a  v1  unchanged
0 versions created, 2 unchanged
published to MLflow: http://127.0.0.1:5113
```

The prompt converted to CRLF — seven line endings rewritten — and published again:

```
$ dossier prompts publish incident-audit
incident-audit · 2 prompts
  incident-audit.extract           b3c909cf  v1  unchanged
  incident-audit.judge.root_cause  0443845a  v1  unchanged
0 versions created, 2 unchanged
published to MLflow: http://127.0.0.1:5113

$ dossier run incident-audit --plan
incident-audit  5 document(s) · model openai:gpt-5.4-mini
compared against 20260923T054607Z-7693
  extract: cached
0 of 1 step(s) would run · nothing written
```

**Why nothing was sent.** `register_prompt` versions unconditionally: called with
the text already at the top of the history, it makes a second version identical to
the first, and a person opening the registry would find two entries to compare that
differ in nothing. So a publish asks for the latest version first and sends nothing
when its `dossier.prompt_hash` is the hash it would publish (R14.4). That read is
the one the one-way promise permits: it decides a write, and nothing it returns
reaches a key, a score or a file (R14.5 row 4).

**Why CRLF is not a change.** The hash is taken over the prompt's text with line
endings normalised, and the template published is that same text — the stage key
has always been taken that way, which is what `--plan` just said. Publishing the
raw bytes would have shown a colleague on another operating system a version that
differs from yours, from the same commit, while the keys both of you computed were
identical (R14.3, R14.4 row 5, spec 005).

Then a real run:

```
$ dossier run incident-audit
run 20260923T054624Z-3ef2 · …/runs/20260923T054624Z-3ef2/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260923T054624Z-3ef2
  extract: 5 document(s) · 5 from cache · 0 failed
```

No line in the stub's log: not one model call.

```
$ python links.py
prompt   incident-audit.extract                     v1  b3c909cf
prompt   incident-audit.judge.root_cause            v1  0443845a
run      dossier-audit/incident-audit/calibrate         calibrate incidents · openai:gpt-5.4-mini                  -
run      dossier-audit/incident-audit/run               20260923T054607Z-7693                                      -
run      dossier-audit/incident-audit/run               20260923T054624Z-3ef2                                      incident-audit.extract v1
run      dossier-audit/incident-audit/sync              sync 20260923T054603Z                                      -
version  m-1ad03e5466074e599e82a85f1d4ec95e  incident-audit.extract v1
```

**Run A links nothing, and keeps linking nothing.** A run links what it rendered
when it runs, to the record it opened (R14.7). Run A's record says what was true
while it ran — nothing was published — and no later command goes back to edit it.

**The version does gain the link.** Both runs built `m-1ad03e54…`: a version is
found by its pipeline and its version hash, which is taken over everything that
produced the answers — the pipeline file, the prompt, the schema, the model and the
converters — so an unchanged pipeline is the same version
(R13.1). The link to a version is a statement about the *version* — what it is made
of — so the run that could first make it made it, and it cost nothing: every stage
was a cache hit (R14.12 row 3).

**The rubric is not on the version.** The version hash covers what produced the
answers, and a rubric scores them. Linked here, it would put a judge's standard on a
version it does not describe (R14.12 row 4).

---

## Task 3 — the judge's standard, linked

```
$ dossier calibrate incident-audit --gold gold/incidents
root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini
recorded to MLflow: dossier-audit/incident-audit/calibrate
```

20 judge calls in the stub's log.

```
$ dossier eval incident-audit --gold gold/incidents
5 documents · 5 fields · overall 100.0%
  loss_amount        100.0%
  resolution_date    100.0%
  severity           100.0%
  affected_systems   100.0%
  root_cause         100.0%   (4 judged)
recorded to MLflow: dossier-audit/incident-audit/eval/incidents
```

4 judge calls.

```
$ python links.py
prompt   incident-audit.extract                     v1  b3c909cf
prompt   incident-audit.judge.root_cause            v1  0443845a
run      dossier-audit/incident-audit/calibrate         calibrate incidents · openai:gpt-5.4-mini                  -
run      dossier-audit/incident-audit/calibrate         calibrate incidents · openai:gpt-5.4-mini                  incident-audit.judge.root_cause v1
run      dossier-audit/incident-audit/eval/incidents    eval 20260923T054624Z-3ef2 · openai:gpt-5.4-mini           incident-audit.judge.root_cause v1
run      dossier-audit/incident-audit/run               20260923T054607Z-7693                                      -
run      dossier-audit/incident-audit/run               20260923T054624Z-3ef2                                      incident-audit.extract v1
run      dossier-audit/incident-audit/sync              sync 20260923T054603Z                                      -
version  m-1ad03e5466074e599e82a85f1d4ec95e  incident-audit.extract v1
```

**Two calibrations, one link.** The first ran during setup, before anything was
published, so there was no version to find; the second links
`incident-audit.judge.root_cause` v1. A calibration is a measurement *of* a rubric,
which makes its record the one where the link matters most (R14.9 row 2).

**Making a version and measuring one.** The eval links the rubric it judged with to
its own run (R14.9). It also takes the version it scored as an input (R13.2) — and
the version still links only `extract`. `dossier run` made the version, so it says
what the version is made of; an eval measured it, and a measurement adds nothing to
what was measured (R14.12 row 5).

**The wrapper.** No. The judge reads the rubric inside a wrapper `dossier` adds — the
material, and the answer format — and only the rubric is published. The link is to
the standard a person wrote. The wrapper is the same for every rubric and lives in
the code, so a change to it is a change to `dossier`: it moves the calibration's
`prompt_hash`, which makes every calibration stale until it is measured again
(R7.19).

---

## Task 4 — a new prompt, a new version, and the old one kept

With the date line added — the prompt is now exercise 12's second version, byte for
byte:

```
$ dossier prompts publish incident-audit
incident-audit · 2 prompts
  incident-audit.extract           f92d511b  v2  created
  incident-audit.judge.root_cause  0443845a  v1  unchanged
1 version created, 1 unchanged
published to MLflow: http://127.0.0.1:5113

$ dossier run incident-audit          # this is run B
run 20260923T054645Z-6fda · …/runs/20260923T054645Z-6fda/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260923T054645Z-6fda
  extract: 5 document(s) · 0 from cache · 0 failed · 1 finding(s)
    PLAY-1002.md  loss_amount: has a value and no source. A figure without evidence is the thing this system exists not to produce (R6.6).

$ dossier eval incident-audit --gold gold/incidents
5 documents · 5 fields · overall 92.0%
  loss_amount         80.0%   <- weakest
    PLAY-1002.md   loss_amount: has a value and no source. A figure without evidence is the thing this system exists not to produce (R6.6).
  resolution_date     80.0%   <- weakest
    PLAY-1001.md   '04.03.2026' is not a well-formed date, so it cannot be compared with '2026-03-04'
  severity           100.0%
  affected_systems   100.0%
  root_cause         100.0%   (4 judged)
recorded to MLflow: dossier-audit/incident-audit/eval/incidents
```

Five model calls for the run and **none** for the eval. The four `root_cause`
answers run B gave are the four run A gave, and a verdict is cached under the
judge model, the rubric, the wrapper, the document and the candidate — nothing
about the run that produced the candidate — so all four were served (R7.18).

With the line taken out again:

```
$ dossier run incident-audit
run 20260923T054657Z-e717 · …/runs/20260923T054657Z-e717/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260923T054657Z-e717
  extract: 5 document(s) · 5 from cache · 0 failed
```

```
$ python links.py
prompt   incident-audit.extract                     v1  b3c909cf
prompt   incident-audit.extract                     v2  f92d511b
prompt   incident-audit.judge.root_cause            v1  0443845a
run      dossier-audit/incident-audit/calibrate         calibrate incidents · openai:gpt-5.4-mini                  -
run      dossier-audit/incident-audit/calibrate         calibrate incidents · openai:gpt-5.4-mini                  incident-audit.judge.root_cause v1
run      dossier-audit/incident-audit/eval/incidents    eval 20260923T054624Z-3ef2 · openai:gpt-5.4-mini           incident-audit.judge.root_cause v1
run      dossier-audit/incident-audit/eval/incidents    eval 20260923T054645Z-6fda · openai:gpt-5.4-mini           incident-audit.judge.root_cause v1
run      dossier-audit/incident-audit/run               20260923T054607Z-7693                                      -
run      dossier-audit/incident-audit/run               20260923T054624Z-3ef2                                      incident-audit.extract v1
run      dossier-audit/incident-audit/run               20260923T054645Z-6fda                                      incident-audit.extract v2
run      dossier-audit/incident-audit/run               20260923T054657Z-e717                                      incident-audit.extract v1
run      dossier-audit/incident-audit/sync              sync 20260923T054603Z                                      -
version  m-1ad03e5466074e599e82a85f1d4ec95e  incident-audit.extract v1
version  m-f450772e99294834a245768975f90777  incident-audit.extract v2
```

**Two versions, one prompt version each.** `m-1ad03e54…` is made of v1 and
`m-f450772e…` of v2 — and the first did not gain v2 when v2 was published, because
it is not made of it.

**Why "newest" is the wrong answer.** The last run rendered `b3c909cf`, and the
version found is the one tagged with the hash the run rendered, not the one at the
top of the history (R14.7 row 1). Taken from the top, its record would say
`extract v2` — confidently, and with nothing to notice it by — and a person diffing
two runs to find what changed would be shown a change that never reached this one.

**No new version.** The last run's version hash is run A's: the same pipeline
file, prompt, schema, model and converters. `dossier` found `m-1ad03e54…` by name and version hash rather than
creating a third, because MLflow creates a new logged model every time it is asked
by name (R13.1).

---

## Task 5 — the change gate, with its standard attached

```
$ dossier eval incident-audit --gold gold/incidents --compare 20260923T054607Z-7693 20260923T054645Z-6fda
compare 20260923T054607Z-7693 -> 20260923T054645Z-6fda · 5 documents · overall 100.0% -> 92.0% (-8.0)
  loss_amount        100.0%  80.0%  -20.0   <- regression
  resolution_date    100.0%  80.0%  -20.0   <- regression
  severity           100.0% 100.0%   +0.0
  affected_systems   100.0% 100.0%   +0.0
  root_cause         100.0% 100.0%   +0.0
recorded to MLflow: dossier-audit/incident-audit/compare/incidents
```

No model call. The comparison's run, read back:

```
mlflow.linkedPrompts   [{"name": "incident-audit.judge.root_cause", "version": "1"}]
dossier.changed_steps  extract (prompt changed)
dossier.regressed      loss_amount, resolution_date
inputs (versions)      ['m-1ad03e5466074e599e82a85f1d4ec95e', 'm-f450772e99294834a245768975f90777']
```

**One link.** Both runs were judged with the rubric in the checkout — never with the
one each was evaluated under when it ran — and a verdict's key holds that rubric's
hash. A comparison is two measurements under one standard, which is what makes its
delta a delta, so there is one standard to link (R14.11). Two links would claim the
sides were judged differently.

**The inputs.** Both pipeline versions (R13.2 row 4): `m-1ad03e54…`, which links
`extract` v1, and `m-f450772e…`, which links `extract` v2.

**The walk.** From the comparison, to `m-f450772e…` among its inputs, to the prompt
version it links, to `incident-audit.extract` on the Prompts page — where v1 and v2
differ by one line:

```
When you report a date, write dates exactly as the note writes them.
```

— which is exactly the line exercise 12 wrote to break two fields. You did not open
either run, either eval, either manifest or the git log. Without the links, the same
question starts from `dossier.changed_steps`, goes to the two runs' `prompt/extract`
params, and ends with two 64-character hashes and a search of the history for the
commits that produced them.

---

## Task 6 — two namespaces, one refused, and a registry taken away

```
$ DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox dossier prompts publish incident-audit
incident-audit · 2 prompts
  sandbox.incident-audit.extract           b3c909cf  v1  created
  sandbox.incident-audit.judge.root_cause  0443845a  v1  created
2 versions created, 0 unchanged
published to MLflow: http://127.0.0.1:5113

$ DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox dossier run incident-audit
run 20260923T054709Z-6dce · …/runs/20260923T054709Z-6dce/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260923T054709Z-6dce
  extract: 5 document(s) · 5 from cache · 0 failed
```

```
$ python links.py
prompt   incident-audit.extract                     v1  b3c909cf
prompt   incident-audit.extract                     v2  f92d511b
prompt   incident-audit.judge.root_cause            v1  0443845a
prompt   sandbox.incident-audit.extract             v1  b3c909cf
prompt   sandbox.incident-audit.judge.root_cause    v1  0443845a
…
run      dossier-audit/incident-audit/run               20260923T054709Z-6dce                                      sandbox.incident-audit.extract v1
…
version  m-1ad03e5466074e599e82a85f1d4ec95e  incident-audit.extract v1, sandbox.incident-audit.extract v1
version  m-f450772e99294834a245768975f90777  incident-audit.extract v2
```

**Two prompts on one version is not a mistake.** Both hold `b3c909cf`: the same
words, published under two names. A prefix namespaces prompt *names*, because a name
is global in MLflow and two checkouts would otherwise publish into one history
(R14.8). A pipeline version is not named by a prefix at all — it is identified by
its version hash, which is taken over what produced the answers (R13.1) — so two
machines running the same pipeline build the same version, and each links it to the
prompts under its own names. Both links are true.

```
$ DOSSIER_MLFLOW_PROMPT_PREFIX=team/a dossier run incident-audit
incident-audit: DOSSIER_MLFLOW_PROMPT_PREFIX='team/a' cannot be published: MLflow rejects '/' in a prompt name, and the prefix goes in front of every one. Choose a prefix holding neither '/' nor ':'.
```

Exit 2, no model call, and five directories under `runs/` before and after it.
**Refused before any work** because it is a setting, and a wrong setting is wrong
before anything is sent: it is checked with the rest of this machine's tracking
configuration, before a document is read or a record opened (R14.10). Checked
where the name is first composed instead — which is how `dossier` behaved before
R14.10 — `eval` and `calibrate` raised a traceback, `calibrate` with its MLflow run
left open, and `run` refused only after its record had opened.

Every prompt deleted from the server, then:

```
prompts left on the server: 0

$ dossier run incident-audit --plan
incident-audit  5 document(s) · model openai:gpt-5.4-mini
compared against 20260923T054709Z-6dce
  extract: cached
0 of 1 step(s) would run · nothing written

$ dossier run incident-audit
run 20260923T054716Z-87d2 · …/runs/20260923T054716Z-87d2/manifest.json
recorded to MLflow: dossier-audit/incident-audit/run · run 20260923T054716Z-87d2
  extract: 5 document(s) · 5 from cache · 0 failed
```

No model call, and:

```
$ diff -r runs/20260923T054607Z-7693/extract runs/20260923T054716Z-87d2/extract
$
```

— run A's artifacts and this run's, byte for byte. The run's record links nothing,
because there was nothing left to find.

**Why nothing could change.** No key, answer or file is ever computed from the
registry. A run renders the prompt file on disk; the registry is asked one question
on the run path — which version carries the hash this run already computed — and
what comes back is a version number, which reaches a link and a tag and nothing
else (R14.5 row 5). A
`PublishedPrompt` has no field that could carry a template back into a run (R14.5).
Loading a prompt from the registry, which is what MLflow's registry is for, would
have made a key depend on what someone last published — reproducible from no
checkout, and a network read on the replay path (R0.10).

---

## What this exercise was really about

Two failures in spec 014 were found by making a call against a real server while
every test was green:

1. the adapter had no `find` at all, while the fake beside it did and every test
   of R14.7 passed — linking would have failed on the first real run;
2. a publish from one checkout arrived as version 2 of another checkout's prompt,
   because a prompt name is global to a server — which is R14.8.

Two more were confirmed live before anything depended on them: `register_prompt`
creates a version every time it is asked, identical text included, so a publish
has to ask before it writes (R14.4); and MLflow keeps a logged model's linked
prompts as a set, so the run at the end of task 4 — back on the first version,
which already linked `extract` v1 — sent a link that changed nothing. That is what
lets `dossier run` link on every run rather than remember which ones already did
(R14.12).

A fake is a claim about somebody else's system. This exercise is the same calls,
made in the order a person makes them, against the system itself.

**Back to:** [the playground index](../README.md).
