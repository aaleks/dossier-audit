# 014 — A pipeline's prompts as MLflow prompt registry versions

**Status:** Partially implemented
**Rules:** R14.1 – R14.7

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
- **Proved by:** `tests/unit/test_R014_7__a_run_links_the_prompt_versions_it_rendered.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | run `20260806T142203Z-4f1a` with tracking on, its `verify` prompt `0e52dd18` published at version 1 and edited to `35d1a8ef` and published at version 2 since | version 1 linked to the MLflow run, not version 2. The run rendered `0e52dd18` and the link says so |
| 2 | the same run, `incident-audit.extract` never published | `extract` links nothing, `verify` and `report` link theirs; the run records and exits exactly as it would have (R10.4) |
| 3 | *counter-example* — `DOSSIER_MLFLOW_ENABLED=false` | no registry read and no link; byte-identical manifest, keys and artifacts (R10.4 row 1) |
| 4 | *counter-example* — `dossier run --plan` and `--replay` | no link and no registry read; neither opens a run to link to (R4.6, R4.7) |
