# 014 — A pipeline's prompts as MLflow prompt registry versions

**Status:** Implemented
**Rules:** R14.1 – R14.12

## Purpose

A prompt is the input to a run that changes most often and is read least easily.
It is hashed into its stage's key and every key downstream of it (R5.2), and its
eight characters reach a provenance record, a trace span and a run name -- but a
person looking at `0e52dd18` in MLflow has no way to see the words behind it, and
no way to diff them against the `35d1a8ef` that produced the run beside it. The
question "what changed between these two runs" is answerable today only by taking
a hash to a git log, which is where a gold set was before spec 012.

So a pipeline's prompts are published to MLflow's prompt registry: one prompt per
step, one per judged field's rubric, versioned, tagged with the hash that enters
the key.

The registry is a **projection**, one way only. Here that is not a restatement of
house style but the whole reason this spec is narrow. MLflow's prompt registry
exists to be loaded from -- `load_prompt("prompts:/verify/3")` is its headline --
and `dossier` declines that half of it, because a prompt fetched at run time
would be:

- an input to a cache key that no checkout can reproduce, breaking R0.4's promise
  that keys are byte-identical across machines given the same prompts;
- a route into a run's behaviour that no pull request passed through, which is
  the working agreement's first rule;
- a network read on the replay path, which R0.10 forbids outright -- and a key
  cannot be recomputed without the prompt's bytes, so `--replay` would have to
  fetch.

`dossier` therefore writes prompts to MLflow and never reads one into a run
(R14.5). That is R12.4's promise for datasets, restated where the temptation is
strongest.

## The command

```
$ dossier prompts publish incident-audit
incident-audit · 4 prompts
  incident-audit.extract           4be9c072  v1  unchanged
  incident-audit.verify            35d1a8ef  v2  created
  incident-audit.report            ca31f5d8  v1  unchanged
  incident-audit.judge.root_cause  f7a2d9c4  v1  unchanged
1 version created, 3 unchanged
published to MLflow: http://localhost:5000
```

Its own command rather than a flag on `dossier run`, for the reason
`dossier dataset publish` is not a flag on `dossier eval` (spec 012): publishing
and running fail for different reasons and are run at different times, and a run
that published as a side effect would mutate shared tracking state on a command
whose contract is that its outputs depend on nothing but its inputs (R10.4).

A prompt is registry-level in MLflow rather than experiment-level, so unlike a
dataset (R12.6) there is no experiment for a publish to join. What ties a version
to the runs it produced is its `dossier.prompt_hash` tag, which is the same value
the run's provenance record already carries -- until R14.7 makes the tie a link.

## What a prompt is called

| Published | Name | From |
|---|---|---|
| a step's prompt | `<pipeline>.<step id>` | `steps[].prompt` |
| a judged field's rubric | `<pipeline>.judge.<field>` | the `judge:` a `free_text` field declares in the step's `output` (R6.10) |

The separator is a dot because MLflow rejects `/` and `:` in a prompt name, so
`incident-audit/verify` is not available. Neither character can reach a name from
a step id, which R3.2 already constrains to `[a-z][a-z0-9_]*`. A pipeline's name
is constrained by nothing except being a directory name -- `path.parent.name`,
one component -- so `/` cannot reach it either and `:` can, on the systems that
allow it in a filename. Both are refused where the name is composed rather than
where it is sent (R14.1 row 5), because the pair is what MLflow rejects and a
check that tracked which half was currently reachable would be a comment
pretending to be code. The pipeline is not droppable either: a
prompt name is global in MLflow, while a prompt file and a rubric are both
resolved against the pipeline's own directory (spec 005). `verify` alone would
interleave two pipelines' edits in one version history.

**A prompt is named for the job it does, not the file it sits in.** Two steps
naming one file publish it twice under their own names; `extract` and `verify`,
which both declare `schemas/incident.yaml`, publish its `root_cause` rubric once,
because that is one job. The alternative -- naming by path -- puts a rename into
the version history of a prompt whose text never changed, and leaves a person
reading `02_verify` in a list where every other line says what it does.

**A name says nothing about the workspace it came from**, and that was missed
when the two paragraphs above were written. Carrying the pipeline was meant to
make a name unique, and it does so only within one workspace: two checkouts with
a pipeline called `incident-audit` -- two people on one team server, or one person
with a playground and a real project -- publish into the same history, each edit
landing as the next version of the other's prompt, and R14.7's lookup can match a
hash that was published from somewhere else. Found live, after R14.1 was MET: a
publish from one workspace arrived as `v2` of a prompt another had published.

So a name may carry a namespace, set per machine in
`DOSSIER_MLFLOW_PROMPT_PREFIX` like every other `DOSSIER_MLFLOW_` variable, and
placed in front with the same dot: `sandbox.incident-audit.extract`. Unset or
empty it is nothing, and every name is byte-identical to what R14.1 and R14.2
compose. That is why R14.8 adds to them rather than superseding them: they say
how a name is composed, and R14.8 says where it lives. A person who never sets
the variable sees no change at all, including in a history already published.

## What a version holds

The **template** is the prompt's text as R5 hashes it: decoded, with line endings
normalised, and not otherwise interpreted. Publishing the raw bytes instead would
show a person a version that differs from the one their colleague published from
the same commit on the other operating system, while the key both runs computed
was identical.

dossier's placeholder syntax is already MLflow's. `{{documents}}` is a variable
to both, so MLflow lists a version's variables without anything being escaped or
rewritten, and R3.6 -- every prompt injects exactly the inputs its step declares
-- makes that list exactly the step's `input`.

Four tags, all under `dossier.`:

| Tag | Holds |
|---|---|
| `dossier.prompt_hash` | the full 64 characters of the hash that enters the stage key (R0.7, R5.2) |
| `dossier.pipeline` | `incident-audit` |
| `dossier.step` / `dossier.field` | `verify` for a step's prompt; `root_cause` for a rubric |
| `dossier.path` | `prompts/02_verify.md`, relative to the pipeline's own directory |

Three things are deliberately **not** on a version, and each would be a version
that moved when the prompt did not:

- the generated JSON Schema `d24c86e1` the step's `output` declares (R6.12). A
  schema is not a prompt; a version that moved when only the schema changed would
  claim the prompt had.
- the pipeline hash `2f60a7d3` (R11.11). It moves with every prompt in the
  pipeline, so it would mark `verify`'s version stale for an edit to `extract`.
- the wrapper dossier puts a rubric in -- the document, the claim, the output
  format (R7.19). A published rubric is the author's rubric, not the judge prompt
  a model is shown, and the tag vocabulary above says `path` for that reason. The
  question "what was the judge actually asked" is answered by the calibration,
  which hashes both (R7.14, R7.19).

The **commit message** is `dossier: <path> <hash8>`, because MLflow's version list
shows it, and a column of blank messages is a version history nobody can read
without opening every row.

## Publishing twice

`register_prompt` creates a new version every time it is called, including for
text identical to the version above it. Left alone, running this command twice
would leave a person comparing `v1` and `v2` that differ in nothing -- the failure
R12.3 exists to prevent for datasets, and sharper here, because there the digest
moved and here it is the artifact itself that duplicates.

So a publish reads the latest version's `dossier.prompt_hash` and sends nothing
when it matches what it would have written. That read is the one the one-way
promise permits, and R14.5 row 4 says why: it decides whether to **write**, and
reaches no key, no score and no file. It is the same comparison R12.3 makes
against `dossier.gold_hash`, against the same objection.

Only the prompt that changed gets a version. A key cascades downstream (R5.2) and
a prompt does not: `report`'s key changes when `verify`'s prompt is edited, and
`report`'s text is still what it was.

## Where the code sits

Publishing returns a version number, which `Tracker`'s contract forbids -- every
method sends and returns nothing, and that is how R0.10 justifies letting tracking
near the network at all. So the registry is a third port beside `DatasetRegistry`,
for the reason spec 012 gave for the second:

```
domain/prompts.py         the projection: a loaded pipeline -> named prompts, pure
domain/ports.py           PromptRegistry: publish(...) -> PublishedPrompt, latest(name)
infrastructure/tracking/  the mlflow.genai prompt calls
application/prompts.py    publish_prompts: compare, send what moved, report
cli/main.py               the `prompts` sub-app, beside `dataset`
```

A `FakePromptRegistry` in the default suite counts publishes and versions as
`FakeDatasetRegistry` counts records and `FakeModelClient` counts calls.

A prompt registry needs a tracking server with a SQL backend, as an evaluation
dataset does: a file-backed store has no model registry behind it, and the
endpoint fails rather than answering. What is checked is that the answer is a
*success*, not that it is any particular failure (R12.5 row 2's reasoning), and a
machine's configuration is refused at startup by name (R14.6, R10.5).

## What this spec does not claim

`dossier calibrate` and `dossier eval` render a judge prompt from a rubric this
command publishes, and neither links the version it used. R14.7 covers
`dossier run` only. The calibration analogue is a rule nobody has written yet
rather than one this spec implies.

A gold set's dataset has the same property and is not namespaced here: it is
named after its directory (R12.1), globally, so two workspaces each holding
`gold/incidents` merge their records into one dataset, keyed by a document key
the two may share. That is spec 012's name and spec 012's decision. It is
recorded rather than folded in because the prefix below was agreed for prompts,
and widening it to a second command's records is a change a person should see
proposed rather than find done.

## Must hold

### R14.1 — every step of a pipeline publishes as one prompt named `<pipeline>.<step id>`

One publish covers the whole pipeline. The name carries the pipeline because a
prompt name is global in MLflow while a prompt file is resolved against the
pipeline's own directory, and it carries the step id rather than the file's name
because that is what every report line, trace span and manifest entry already
says.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.prompts.publish_set`)
- **Proved by:** `tests/acceptance/test_R014_1__a_pipeline_publishes_one_prompt_per_step.py`, `tests/unit/test_R014_1__a_prompt_is_named_for_its_pipeline_and_step.py`, `tests/unit/test_R014_1__a_pipeline_contributes_one_prompt_per_step.py`, `tests/unit/test_R014_1__publishing_sends_every_prompt_the_pipeline_names.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier prompts publish incident-audit`, whose steps are `extract`, `verify`, `report` | 3 prompts named for those steps -- `incident-audit.extract`, `incident-audit.verify`, `incident-audit.report` -- one version each, beside whatever rubric R14.2 publishes; the terminal names each with its hash and version; exit 0 |
| 2 | `postmortem-review` whose `verify` step names a prompt file byte-identical to `incident-audit`'s | a separate prompt `postmortem-review.verify` at version 1; `incident-audit.verify` untouched. One pipeline's step is one prompt, and a shared file is not a shared history |
| 3 | two steps of `incident-audit` naming the same `prompts/02_verify.md` | 2 prompts, one per step, each at version 1. A prompt is named for the job it does, not the file it sits in |
| 4 | *counter-example* — a step naming a prompt file that is not there | exit 2 from load, as R3.6 already refuses it; 0 prompts registered. A publish reads the pipeline the run reads, and does not get further than the run would |
| 5 | *counter-example* — a pipeline directory named `incident:audit`, legal on Linux and macOS | `prompt_name` raises rather than composing `incident:audit.verify`; nothing is sent. A pipeline's name is `path.parent.name`, one component, so `/` cannot reach it and `:` can -- `dossier prompts publish foo/bar` resolves `pipelines/foo/bar/` and is named `bar`, which is legal. Refused where the name is composed rather than by an MLflow traceback partway through a publish |

### R14.2 — every judged field publishes its rubric as one prompt named `<pipeline>.judge.<field>`

The rubric is a prompt by every measure that matters: an author writes it, an
edit to it changes what a model is asked, and its hash gates a calibration
(R7.14). It is resolved against the pipeline's own directory like `prompts/`, so
its name carries the pipeline too.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.prompts.publish_set`)
- **Proved by:** `tests/unit/test_R014_2__a_judged_field_publishes_its_rubric.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incident.yaml` declaring `root_cause: {kind: free_text, judge: rubrics/root_cause.md}` | a prompt `incident-audit.judge.root_cause` holding that file's text, tagged `dossier.field` `root_cause` and `dossier.path` `rubrics/root_cause.md` |
| 2 | `extract` and `verify` both declaring `output: schemas/incident.yaml` | `incident-audit.judge.root_cause` published once, not twice. Two steps reading one declaration is one job, and the name is the field's rather than the step's for exactly this reason |
| 3 | *counter-example* — `loss_amount`, `resolution_date`, `severity`, declared with no `judge` | no prompt for any of them; a field scored by string comparison has no rubric to publish (R6.10) |
| 4 | *counter-example* — the judge prompt `dossier` renders around that rubric (R7.19) | not published, and not part of `incident-audit.judge.root_cause`'s template. What a version holds is the author's file; what the model was asked is in the calibration, which hashes both |

### R14.3 — a version holds the text the prompt's hash was taken over, tagged with that hash

The tie between a version in MLflow and a key in a provenance record. Without the
tag a person has a prompt they can read and no way to know which run rendered it.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.prompts.publish_set`)
- **Proved by:** `tests/unit/test_R014_3__a_version_holds_the_text_its_hash_was_taken_over.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `prompts/02_verify.md`, hash `0e52dd18` | the template is that file decoded with line endings normalised (R5); tags `dossier.prompt_hash` `0e52dd18…` in all 64 characters (R0.7), `dossier.pipeline` `incident-audit`, `dossier.step` `verify`, `dossier.path` `prompts/02_verify.md` |
| 2 | that prompt holding `{{documents}}`, `{{extract}}` and `{{reference}}` | MLflow records those three variables, nothing escaped and nothing rewritten; the set is the step's declared `input`, which R3.6 already requires |
| 3 | the same publish | the commit message reads `dossier: prompts/02_verify.md 0e52dd18`; a version list of blank messages is one nobody reads without opening every row |
| 4 | *counter-example* — the generated JSON Schema `d24c86e1` the step's `output` declares | not on the version. A version that moved when only the schema changed would claim the prompt had |
| 5 | *counter-example* — the pipeline hash `2f60a7d3` | not on the version. It moves with every prompt in the pipeline, so it would mark `verify` stale for an edit to `extract` |

### R14.4 — publishing a prompt whose hash is already the latest version's sends nothing

`register_prompt` versions unconditionally, so this is the rule that keeps a
version history readable. Publishing twice is a no-op a person can run without
thinking about it.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.prompts.publish_prompts`)
- **Proved by:** `tests/unit/test_R014_4__republishing_an_unchanged_prompt_adds_no_version.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incident-audit` published, nothing edited, published again | 4 prompts, each still at version 1; 0 versions created the second time; the terminal says `0 versions created, 4 unchanged` |
| 2 | `prompts/02_verify.md` edited from `0e52dd18` to `35d1a8ef`, then published | `incident-audit.verify` at version 2; `extract`, `report` and `judge.root_cause` still at version 1. A key cascades downstream (R5.2) and a prompt does not |
| 3 | a fourth step `summarise` added to the pipeline, then published | a new prompt `incident-audit.summarise` at version 1; the three already there unchanged, 1 version created |
| 4 | *counter-example* — trailing whitespace added to `prompts/03_report.md` | a new version. The hash moves (R5.2 row 4), and a "harmless" edit is not distinguishable from a real one |
| 5 | *counter-example* — `prompts/01_extract.md` rewritten with CRLF line endings and no other change | no new version. Line endings are normalised before hashing (R5), so the key did not move and neither does the registry |

### R14.5 — no prompt version is ever read back into a rendered prompt, a key, a score or a file

The one-way promise this spec opens with, and the reason it is narrow. What may
never cross the port is a prompt's **text**: `PublishedPrompt` has no field to
carry one, so no method can return one however the port grows. A version number
may cross, and reaches a tag, a link and the terminal (row 3).

That is the promise worth keeping. "Read nothing" would have been easier to
check and would have banned the comparison that stops a redundant version
(R14.4) and the lookup that links a run to what it rendered (R14.7) -- neither of
which puts a word of anyone's prompt into a run.

One read happens inside MLflow rather than in dossier, and is named here so it
is not mistaken for a breach. `MlflowClient.link_prompt_version_to_run` given a
`prompts:/<name>/<version>` URI resolves it with `load_prompt` before linking,
so the link R14.7 and R14.9 make fetches the version it links to. The template
goes nowhere: `rendered_prompt` returns `None`, the port has no field to carry
text, and no `load_prompt` appears under `src/`. Avoiding the fetch would mean
MLflow's private registry client, or a `PromptVersion` built around a template
dossier does not hold -- both worse than a read that decides nothing.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R014_5__a_prompt_version_is_never_read_back_into_a_run.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incident-audit.verify` at version 2 holding `35d1a8ef`'s text, while `prompts/02_verify.md` on disk still holds `0e52dd18`'s | the run renders the file; the `verify` key is `9f21c0a4` as before; the published version contributes to no key, artifact or manifest |
| 2 | every prompt deleted from the MLflow registry between two runs | the second run exits 0 with byte-identical keys and a full cache hit. A registry that is gone changes nothing, because nothing was reading it |
| 3 | a publish returning version `2` | it reaches the terminal line and nothing else: no file under `runs/`, `gold/`, `.dossier/` or the pipeline's own directory holds a version number (R10.4 row 2, R12.4 row 3) |
| 4 | *counter-example* — the publish reading the latest version's `dossier.prompt_hash` before deciding to send | permitted. It decides a **write**, as R12.3's comparison against `dossier.gold_hash` does, and nothing about it reaches an output |
| 5 | *counter-example* — `dossier run` asking the registry which version carries the hash it rendered (R14.7) | permitted, and the narrowest read on the run path there is: it takes a hash the run already computed and gets back a **version number**, which reaches a link and a tag. No template crosses the port -- `PublishedPrompt` has no field to carry one -- so the text a run renders still comes only from the file on disk |

### R14.6 — publishing with tracking off, or to a server with no prompt registry, is refused by name before anything is sent

Both are a machine's configuration, and both are refused where R12.5 and R10.5
refuse theirs: at startup, naming the thing to fix.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R014_6__publishing_prompts_is_refused_by_name.py`, `tests/integration/test_R014_6__mlflow_prompt_registry_adapter.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_ENABLED=false`, `dossier prompts publish incident-audit` | exit 2 naming `DOSSIER_MLFLOW_ENABLED`; 0 requests sent. Like a dataset publish and unlike a run, this command's whole output is the record |
| 2 | tracking enabled against a file-backed server, whose prompt search answers with anything but a success | exit 2 naming the status and the SQL backend a prompt registry needs; 0 versions sent |
| 3 | tracking enabled, nothing answering at `http://localhost:5000` | exit 2 naming the URI, as R10.5 row 1 refuses a run |
| 4 | tracking enabled, the `tracking` extra not installed | exit 2 naming `dossier[tracking]` (R10.5 row 3) |
| 5 | *counter-example* — `dossier run incident-audit` against that same file-backed server | runs and exits 0. A run publishes no prompt and needs no registry |

### R14.7 — a run's MLflow record links the prompt version each step rendered, and links nothing for a prompt that was never published

What the publishing is for: opening a run and reading the words that produced it.
The version is found by the `dossier.prompt_hash` the run already holds, so the
link is a statement about the prompt that ran rather than about what is newest.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R014_7__a_run_links_the_prompt_versions_it_rendered.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | run `20260806T142203Z-4f1a` with tracking on, its `verify` prompt `0e52dd18` published at version 1 and edited to `35d1a8ef` and published at version 2 since | version 1 linked to the MLflow run, not version 2. The run rendered `0e52dd18` and the link says so |
| 2 | the same run, `incident-audit.extract` never published | `extract` links nothing, `verify` and `report` link theirs; the run records and exits exactly as it would have (R10.4) |
| 3 | *counter-example* — `DOSSIER_MLFLOW_ENABLED=false` | no registry read and no link; byte-identical manifest, keys and artifacts (R10.4 row 1) |
| 4 | *counter-example* — `dossier run --plan` and `--replay` | no link and no registry read; neither opens a run to link to (R4.6, R4.7) |

### R14.8 — a configured `DOSSIER_MLFLOW_PROMPT_PREFIX` goes in front of every prompt name, and an unset one changes none

The namespace a name was missing. Per machine, read with the rest of the
tracking configuration and never from committed files, because which namespace a
checkout publishes into is a fact about where it runs rather than about the
pipeline (R10.1, R9.2). Applied to every name a publish sends and every name a
run looks up, so the two can only agree.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.prompts.prompt_name`)
- **Proved by:** `tests/acceptance/test_R014_8__a_prompt_prefix_namespaces_every_name.py`, `tests/unit/test_R014_8__a_prefix_goes_in_front_of_every_prompt_name.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox`, `dossier prompts publish incident-audit` | `sandbox.incident-audit.extract`, `sandbox.incident-audit.verify`, `sandbox.incident-audit.report` and `sandbox.incident-audit.judge.root_cause`, each at version 1; the terminal names each as it was published |
| 2 | two workspaces each holding `incident-audit`, one publishing with `sandbox` and one with no prefix | two prompts, `sandbox.incident-audit.extract` and `incident-audit.extract`, each at version 1. Without the prefix the second publish would have been version 2 of the first workspace's prompt, which is the failure this rule exists for |
| 3 | published under `sandbox`, then `dossier run incident-audit` on the same machine | the run looks up and links `sandbox.incident-audit.extract` at the version carrying the hash it rendered (R14.7). A run asks under the name it would have published under |
| 4 | *counter-example* — unset, or set to the empty string | every name byte-identical to R14.1's and R14.2's -- `incident-audit.extract`. A prompt published before this rule is found, compared and not sent again (R14.4) |
| 5 | *counter-example* — `DOSSIER_MLFLOW_PROMPT_PREFIX=team/a` | exit 2 naming `/` and `DOSSIER_MLFLOW_PROMPT_PREFIX`; 0 prompts sent. The refusal R14.1 row 5 makes of a pipeline name, on the other component nothing else constrains |
| 6 | *counter-example* — published under `sandbox`, then run on a machine with no prefix | the run looks up `incident-audit.extract`, finds nothing, links nothing, and exits as it would have (R14.7 row 2). A prefix is per machine; two machines that disagree about it are the one case it cannot help |

### R14.9 — a judge's MLflow record links the rubric version it judged with, and links nothing for a field it did not judge

R14.7 for the other half of what R14.2 publishes. A rubric's words are what a
verdict is reached under, and an eval whose `root_cause` figure moved is asked
first whether the judge's standard moved with it. Without a link that question
goes to a hash and a git log -- the question R14.7 closed for a run's prompts.

Two records judge with a rubric, and each links the one it used:
`dossier eval` for every judged field it may report -- every field R7.15 did not
withhold, whether its verdicts were asked for or served from the `judge` cache,
because a cached verdict's key holds the same rubric hash (R7.18, R7.19) -- and
`dossier calibrate` for every field it measured, since a calibration is a
measurement *of* that rubric. The version is found by the rubric's
`dossier.prompt_hash`, which is the `text_hash` the gate already compares
(R7.15), never by recency.

**The linked version is the rubric an author wrote, not the prompt the judge
read.** A calibration is stale when either the rubric or the wrapper dossier puts
round it moves (R7.19), and only the first is published (R14.2). A person opening
the link reads the standard; the wrapper is the same text for every rubric and
lives in the code, where a change to it is a change to dossier.

A withheld field links nothing. Nothing was judged with its rubric, and a
rubric edited since its calibration -- the commonest reason for withholding
(R7.15) -- would otherwise link words no reported figure came from.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/acceptance/test_R014_9__a_judge_links_the_rubric_version_it_judged_with.py`, `tests/unit/test_R014_9__a_judge_looks_up_the_rubric_of_every_field_it_may_report.py`, `tests/unit/test_R014_9__a_record_links_the_version_carrying_the_hash_it_used.py`, `tests/unit/test_R014_9__a_calibration_links_the_rubric_it_measured_once.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier eval incident-audit` of run `20260806T142203Z-4f1a`, tracking on, `root_cause` calibrated against rubric `f7a2d9c4`, published at version 1; a draft rubric published as version 2 and reverted in the checkout since | version 1 linked to the eval's MLflow run, not version 2. The eval judged with `f7a2d9c4`'s words and the link says so |
| 2 | `dossier calibrate incident-audit --gold gold/incidents`, the same rubric at version 1 | version 1 linked to the calibration's MLflow run, once, although both the grounded and the described judge were measured against it (R7.22) |
| 3 | the eval of row 1 run a second time, every verdict served from the `judge` cache and 0 judge calls | version 1 linked all the same. The verdicts were reached under that rubric; where they were read from is not what the link is about |
| 4 | `DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox`, the rubric published under it | the eval looks up and links `sandbox.incident-audit.judge.root_cause` (R14.8) |
| 5 | *counter-example* — `root_cause` withheld as stale, its rubric edited since calibration | no registry read for `root_cause` and no link; the eval prints, records and exits exactly as it would have |
| 6 | *counter-example* — `incident-audit.judge.root_cause` never published | links nothing; the eval and the calibration record and exit exactly as they would have (R10.4, R14.7 row 2) |
| 7 | *counter-example* — `DOSSIER_MLFLOW_ENABLED=false` | no registry read and no link, on `eval` and on `calibrate` |
| 8 | *counter-example* — `dossier run incident-audit`, the rubric published | no rubric linked to the run. A run judges nothing; what it links is the prompts it rendered (R14.7). A comparison does judge, both sides with one rubric, and links it -- which is R14.11 |

### R14.10 — a prefix MLflow would reject is refused before any work by every command that records, and by none while tracking is off

R14.8 row 5 refuses `team/a` where a publish composes a name. Every other
command that looks a name up met it later and worse: `dossier run` refused it
through a handler written for plan resolution, after its MLflow run was open,
and `dossier eval` and `dossier calibrate` raised a traceback -- the second of
them with its run left open. A setting that is wrong is wrong before anything
is sent, so it is refused where the rest of this machine's tracking settings
are: before any work, with exit 2 naming the variable (R10.1, R10.5).

Every command that records, not only the three that look a name up. The
prefix is part of this machine's tracking configuration, and a person told at
`dossier sync` fixes it before the run that would have needed it -- as a
mistyped `DOSSIER_MLFLOW_ENABLED` is refused by every command rather than by
the ones that would have recorded most.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main._tracking_for`), over `dossier.domain.prompts.check_prompt_prefix`
- **Proved by:** `tests/acceptance/test_R014_10__a_prefix_mlflow_would_reject_is_refused_before_any_work.py`, `tests/unit/test_R014_10__a_prefix_mlflow_would_reject_is_refused_by_name.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_MLFLOW_PROMPT_PREFIX=team/a`, tracking on, `dossier eval incident-audit --gold gold/incidents` | exit 2 naming `/` and `DOSSIER_MLFLOW_PROMPT_PREFIX`; 0 judge calls and 0 MLflow runs opened |
| 2 | the same prefix, `dossier calibrate incident-audit --gold gold/incidents` | exit 2 naming the variable; 0 judge calls and 0 MLflow runs opened |
| 3 | the same prefix, `dossier run incident-audit` | exit 2 naming the variable; 0 model calls and 0 MLflow runs opened. Refused before the run opens, not after |
| 4 | the same prefix, `dossier sync incident-audit` | exit 2 naming the variable; 0 items fetched. The setting is refused where it is read, not where it would first have mattered |
| 5 | *counter-example* — `team/a`, `DOSSIER_MLFLOW_ENABLED=false`, `dossier run incident-audit` | exit 0, as the run would have. Nothing is recorded or looked up, so nothing reads the prefix (R14.7 row 3) |
| 6 | *counter-example* — `DOSSIER_MLFLOW_PROMPT_PREFIX=sandbox` | nothing refused; every command records as R14.8 row 1 names |

### R14.11 — a comparison's MLflow record links the rubric version both its sides were judged with

R14.9 for the other command that judges. A comparison reproduces two runs and
puts both through the judge (R7.17 row 7), and its record holds the delta the
change gate exists to produce (R11.8) -- the figure a person is most likely to
quote, and so the one whose standard they most need to be able to open.

One rubric per field, not one per side. Both runs are judged with the rubric in
the checkout, never with the one each was evaluated under when it ran, and a
verdict's key holds that rubric's hash (R7.18, R7.19): a comparison is two
measurements under one standard, which is what makes the delta a delta. Gated
as an eval is, so a withheld field links nothing, for R14.9's reason.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.record_comparison`)
- **Proved by:** `tests/acceptance/test_R014_11__a_comparison_links_the_rubric_it_judged_with.py`, `tests/unit/test_R014_11__a_comparison_records_its_rubric_link_inside_its_run.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier eval incident-audit --gold gold/incidents --compare 20260806T142203Z-4f1a 20260907T090000Z-bbbb`, `root_cause` calibrated against rubric `f7a2d9c4` at version 1; a draft published as version 2 and reverted in the checkout since | version 1 linked to the comparison's MLflow run, once, not version 2 and not once per side |
| 2 | *counter-example* — `root_cause` withheld as stale | no registry read for `root_cause` and no link; the comparison prints the reason on both sides and records exactly as it would have |
| 3 | *counter-example* — `incident-audit.judge.root_cause` never published | links nothing; the comparison records and exits exactly as it would have (R10.4) |
| 4 | *counter-example* — `DOSSIER_MLFLOW_ENABLED=false` | no registry read and no link |
| 5 | *counter-example* — the two runs cover different documents | refused before any record, as R11.8 row 4 refuses it: no MLflow run, so no registry read and no link |

### R14.12 — a pipeline version links the prompt version each of its steps rendered

R14.7 links a run to the prompts it rendered. The pipeline version that run
built (spec 013) is made of exactly those prompts -- its version hash is taken
over their hashes (R13.1) -- and the Models tab, where two versions are
compared, showed neither. MLflow links a prompt version to a logged model as it
does to a run, so the version says what it is made of on its own page.

Linked by `dossier run`, the command that builds the version (R13.2), from the
same lookups R14.7 makes: each step's prompt is found once, by its hash, and
the version found is linked to both. A step whose prompt was published after
the run links at the next run of that version -- one whose every stage is a
cache hit, asking no model -- because the link is to the version rather than to
a run. MLflow holds a model's linked prompts as one set, so linking one twice
changes nothing.

A rubric is not linked to a version. The version hash covers what produced the
answers and a rubric scores them (R13.1); a rubric linked here would put a
judge's standard on a version it does not describe.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R014_12__a_pipeline_version_links_the_prompts_its_steps_rendered.py`, `tests/unit/test_R014_12__a_version_link_that_fails_costs_the_link_only.py`, `tests/unit/test_R014_12__one_lookup_links_the_run_and_the_version.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier run incident-audit`, tracking on, `extract`, `verify` and `report` published at the hashes the run rendered | the pipeline version the run registered links `incident-audit.extract`, `incident-audit.verify` and `incident-audit.report`, each at the version carrying that hash; the run links the same three (R14.7) |
| 2 | `verify` published at version 1 as `0e52dd18` and at version 2 as `35d1a8ef`; the run renders `0e52dd18` | the version links `verify` at version 1, not version 2 |
| 3 | `extract` never published before the first run; published after it; `dossier run incident-audit` again, every stage a cache hit and 0 model calls | the version now links `extract` as well. The same version, completed by a run that cost nothing |
| 4 | *counter-example* — `incident-audit.judge.root_cause` published | not linked to the version. A rubric scores the answers, and the version hash does not cover it (R13.1) |
| 5 | *counter-example* — `dossier eval incident-audit --gold gold/incidents` | no step prompt linked to the version. An eval measures a version it did not make (R13.2 row 2); what it links is its rubric, to its own run (R14.9) |
| 6 | *counter-example* — the version registry cannot hold a logged model (R13.5) | no version link; the run still links its prompts to itself (R14.7) and exits exactly as it would have |
| 7 | *counter-example* — `DOSSIER_MLFLOW_ENABLED=false` | no registry read and no link |
