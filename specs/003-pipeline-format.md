# 003 — Configuration format

**Status:** Partially implemented
**Rules:** R3.1 – R3.19

## Purpose

Two files describe a use case. Both are validated against pydantic models at load
time; an invalid file is a hard error before any work begins, because every later
stage is expensive and a configuration mistake is cheap to catch here.

## `sources.yaml`

```yaml
sources:
  - id: incidents-manual
    type: folder
    path: inbox/incidents/

  - id: incidents-jira
    type: jira
    url: https://jira.example.internal
    query: project = INC AND type = Incident
    token_env: DOSSIER_JIRA_TOKEN
    fields: [key, summary, status, created, resolution, description, comments]
    watermark_overlap: 24h

  - id: procedures-confluence
    type: confluence
    url: https://confluence.example.internal
    query: space = OPS AND label = procedure
    token_env: DOSSIER_CONFLUENCE_TOKEN
    export: pdf
```

`fields` doubles as the normalisation projection for hashing (spec 002). It is
**optional**, and its absence is meaningful rather than a default: a source with
no `fields` has its payload hashed exactly as received (R2.10). That is why the
folder source above declares none — every byte of a dropped file counts.

An empty list is not the same thing and is rejected: `fields: []` is a projection
onto nothing, which no payload satisfies.

The keys every source takes are `id`, `type`, `fields`, `convert` and
`watermark_overlap`. Anything else -- `path`, `query`, `export` -- belongs to the
source's type, and its connector declares it; the loader checks a source against
both before anything runs (R1.10).

`convert` takes one of two shapes. A list of kinds is asked of every document
the source holds. A map from a media type to its kinds is asked only of the
documents of that type (R8.26), and a type mapped to `[]` is not read at all
(R8.27). A document a map does not name, like every document of a source with
no `convert`, gets the default kind for its media type (R8.10).

## `pipelines/<name>/pipeline.yaml`

```yaml
sources:   [incidents-jira, incidents-manual]   # documents to audit
reference: [procedures-confluence]              # context, not audited
gold:      gold/incidents/

model:     anthropic:claude-sonnet-4-5-20250929  # pinned, no aliases

steps:
  - id: extract
    prompt: prompts/01_extract.md
    input: documents
    mode: per_file
    output: schemas/incident.yaml
    model: ollama:qwen2.5:7b@sha256:7f3c29a1       # this step only (R3.14)

  - id: verify
    prompt: prompts/02_verify.md
    input: [documents, extract, reference]
    mode: per_file
    output: schemas/incident.yaml

  - id: report
    prompt: prompts/03_report.md
    input: verify
    mode: aggregate
```

### Input keywords

| Value | Resolves to |
|---|---|
| `documents` | Converted documents from `sources` |
| `reference` | Converted documents from `reference`: context shown to every call, never audited (R3.17, R3.18) |
| `<step id>` | That step's outputs |
| `previous` | The immediately preceding step (sugar — see spec 004) |
| `previous(n)` | The preceding `n` steps (sugar — see spec 004) |

### Models

`model:` at the top is the pipeline's, and every step that names none is asked
with it. A step may name its own, which is the one it is asked with instead: the
common shape is a cheap model to extract and a strong one to verify and report
(R3.14). The pipeline's `model:` stays required -- it is the default, and it is
what judges an eval (spec 007).

### Modes

- `per_file` — one model call per document; output is one artifact per document.
- `aggregate` — one model call over all inputs; output is a single artifact.
- `per_part` — one model call per part of a container, such as a page image;
  output is one artifact per part (R3.12).
- `per_group` — one model call per group of documents, a group being the documents
  whose keys share a first segment; output is one artifact per group (R3.15).

An `aggregate` step's single artifact is filed under the document key `*`, and
that key is reserved: a source may not hold a document called `*`. The step read
every document, so naming it after any one of them would be wrong, and leaving it
unnamed would give a report no way to say which step a failure came from —
`report failed on *` is the line a person sees.

## Prompt files

Multiple inputs are injected under distinct labelled tags, never concatenated:

```markdown
<source_document>{{documents}}</source_document>
<extraction>{{extract}}</extraction>
<procedure>{{reference}}</procedure>
```

Every placeholder holds documents wrapped in a tag naming the key each came
from (R3.13). A `per_file` step's placeholder holds the one document that call
is about; an `aggregate` step's holds every document:

```markdown
<extraction>
<document key="INC-4821">{...}</document>
<document key="INC-4822">{...}</document>
</extraction>
```

Wrapped rather than concatenated, for the same reason the inputs above are: a
model asked to attribute a finding needs to know which document it read it in,
and `source.document` must name one of them for the field to be grounded (R6.4).
A `per_file` step is wrapped for that reason too, and used not to be: a stage
asked to carry a key it was never shown has to guess one, and a guessed key is
`invalid` under R6.3 however right the value beside it is (R3.13).
Documents appear in key order, so the same set of inputs produces the same prompt
on every machine (R0.4).

## Existing options considered

No established tool applies: a group is computed from this project's own keys, and
its consequences are this project's cache, manifest and scoring. Three places a
group could come from were weighed:

| Option | For | Against |
|---|---|---|
| **The key's first segment** (adopted) | no configuration; Jira, Confluence and folder sources already key a file under what it belongs to; a replay recomposes groups from the keys its manifest pins (R4.15) | a folder of contracts named by convention must be sorted into subfolders first |
| A pattern per source, `group: <regex>` | handles a flat folder named by convention | a regex for an analyst to write and get wrong, one more key checked at load time (R1.10), and the pattern would enter every key |
| A committed file listing each group's members | explicit and reviewable | kept by hand, a new document is in no group until someone adds it, and the file would have to be pinned in the manifest |

Decided 2026-09-27 by the project owner.

## Must hold

### R3.1 — an invalid configuration file fails at load time, naming file, line and key

An unknown key, a missing required key or a wrong type stops the run before any
work begins. The message names all three, because a schema error that says only
"validation failed" costs more than the error it reports.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R003_1__invalid_config_fails_naming_file_line_and_key.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `sources.yaml` with `pth: inbox/incidents/` | error naming `sources.yaml`, the line, and `pth`, and suggesting `path` |
| 2 | a source with `type: folder` and no `path` | error naming the missing required key |
| 3 | `watermark_overlap: 24` | type error; the field is a duration such as `24h`, not a bare number |
| 4 | *counter-example* — a valid file with keys in an unusual order | accepted; key order in YAML carries no meaning |

### R3.2 — a step id is unique within a pipeline and matches `[a-z][a-z0-9_]*`

Step ids become directory names and appear in cache keys, so they must be stable
and unambiguous.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.pipeline.validate_step_ids`)
- **Proved by:** `tests/unit/test_R003_2__step_ids_are_unique_and_well_formed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | steps `extract`, `verify`, `report` | accepted |
| 2 | two steps both named `verify` | load-time error naming the duplicate and both lines |
| 3 | a step named `Verify-2` | load-time error; uppercase and `-` are not permitted |
| 4 | *counter-example* — a step named `verify_2` | accepted; digits and underscores are allowed after the first character |

### R3.3 — a step may only reference an id that exists and appears before it

Forward and self references are the two ways a linear pipeline stops being
linear, and both are cheap to reject.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.pipeline.validate_references`)
- **Proved by:** `tests/unit/test_R003_3__forward_and_unknown_references_are_rejected.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `verify` with `input: [documents, extract]` | accepted; `extract` precedes it |
| 2 | `extract` with `input: verify` | load-time error; `verify` appears later |
| 3 | `report` with `input: enrich`, no such step | load-time error naming the unknown id |
| 4 | *counter-example* — `verify` with `input: reference` | accepted; `documents` and `reference` are source keywords, not step ids |
| 5 | *counter-example* — `verify` with `input: previous` | accepted; `previous` is sugar, not an id, and there is nothing here to resolve it against. Whether it has a predecessor is spec 004's question (R4.3) |

### R3.4 — a model value that is not fully version-pinned is rejected at load time

The load-time half of R0.6.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R003_4__unpinned_model_is_rejected_at_load_time.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `model: anthropic:claude-sonnet-4-5-20250929` | accepted |
| 2 | `model: anthropic:claude-sonnet-4-5` | load-time error naming `pipeline.yaml`, the line and the alias |
| 3 | `model` absent from `pipeline.yaml` | load-time error; there is no default model |
| 4 | *counter-example* — `dossier run --plan`, which makes no model calls | still rejected at load time; validity does not depend on whether the model is used (R4.6) |

### R3.5 — every `output` path resolves to a schema file that itself loads and validates

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R003_5__output_schemas_must_load_and_validate.py`
- **Status:** SUPERSEDED by R3.10

| # | Given | Then |
|---|-------|------|
| 1 | `output: schemas/incident.json`, present and valid | accepted; its hash `b81f0c6d` is recorded for keying |
| 2 | `output: schemas/missing.json` | load-time error naming the path and the step |
| 3 | `output: schemas/incident.json` containing malformed JSON | load-time error naming the file and the parse position |
| 4 | *counter-example* — the `report` step, which declares no `output` | accepted; `aggregate` steps may produce prose, and no schema means no schema check |

### R3.6 — prompt placeholders and declared inputs correspond exactly

Every `{{...}}` in a prompt is a declared input of that step, and every declared
input appears in the prompt. Either mismatch is a load-time error: an unused
input is a silent no-op, and an unfilled placeholder reaches the model as
literal braces.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.prompts.check_placeholders`)
- **Proved by:** `tests/unit/test_R003_6__prompt_placeholders_match_declared_inputs.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `input: [documents, extract]`, prompt using `{{documents}}` and `{{extract}}` | accepted |
| 2 | `input: [documents, extract]`, prompt using only `{{documents}}` | load-time error; `extract` is declared and never injected |
| 3 | `input: documents`, prompt using `{{documents}}` and `{{reference}}` | load-time error; `reference` is injected and never declared |
| 4 | *counter-example* — a prompt containing the literal text `{{` inside a fenced code block | not treated as a placeholder; example code in a prompt is not an input |

### R3.7 — a pipeline declaring `gold` must point at a directory that exists and conforms to spec 007

`gold` is resolved against the workspace -- the directory `dossier` runs in --
and not against the pipeline's own directory, as `prompts/` and `output` are. A
gold set is a workspace asset: spec 007 keeps it at `gold/<name>/`, one set can
serve several pipelines, and `dossier eval --gold` names the same directory the
same way.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R003_7__gold_directory_is_validated_at_load_time.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold: gold/incidents/` holding one valid file per document | accepted |
| 2 | `gold: gold/incidents/` which does not exist | load-time error naming the path |
| 3 | a gold file missing `verified_by` | load-time error naming the file and the missing key (R7.7) |
| 4 | *counter-example* — a pipeline with no `gold` key at all | accepted; `dossier run` works without a gold set, and only `dossier eval` requires one |

### R3.8 — loading a valid configuration performs no network I/O and no model calls

Loading is a pure function of files on disk. It is also the step that runs before
every other step, so anything expensive here is paid on every command.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R003_8__config_loading_touches_nothing_external.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a valid `sources.yaml` and `pipeline.yaml` loaded with the network stubbed to raise | loads successfully |
| 2 | the same, with the model client stubbed to raise on any call | loads successfully |
| 3 | `type: jira` with `JIRA_TOKEN` unset | loads successfully; credentials are checked when a connector is used, not when config is read |
| 4 | *counter-example* — `dossier sync` immediately after loading | reaches the network, as it must; the rule constrains loading, not the command containing it |

### R3.9 — `fields` is optional, and an empty `fields` list is rejected

Omitting `fields` selects raw-payload hashing (R2.10). Declaring it empty selects
a projection onto no fields, which is never what anyone means.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R003_9__fields_is_optional_and_never_empty.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `incidents-manual` with `type: folder` and no `fields` | accepted; the source hashes payloads as received |
| 2 | `incidents-jira` with `fields: [key, summary, status]` | accepted; those three form the projection and the configuration hash |
| 3 | any source with `fields: []` | load-time error naming the file, the line and the source id |
| 4 | *counter-example* — a source declaring `fields` whose payload turns out to be a PDF | not a load-time error; whether a projection can be applied to a payload is a sync-time concern, and load time never fetches one (R3.8) |

### R3.10 — every `output` path resolves to a field declaration that loads and declares valid kinds

Supersedes R3.5, which checked the same thing about a hand-written JSON Schema.
A step's `output` now names a YAML field declaration and the JSON Schema is
generated from it (R6.10), so what must be checked at load time changed with it:
not "does this JSON parse" but "are these fields declared in a way that can be
scored".

Still at load time, and still before anything runs. A field declaration that
cannot be read is a pipeline that cannot be scored, and finding that out after a
run has been paid for is the whole failure this rule exists to prevent.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/acceptance/test_R003_10__output_declarations_must_load_and_validate.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `output: schemas/incident.yaml`, present and declaring five valid fields | accepted; its hash `6e0d4b27` is recorded for keying (R6.11) |
| 2 | `output: schemas/missing.yaml` | load-time error naming the path and the step |
| 3 | `output: schemas/incident.yaml` containing malformed YAML | load-time error naming the file and the parse position |
| 4 | a field declaring a `kind` that is not one of the five | load-time error naming the field and listing the kinds that exist |
| 5 | *counter-example* — the `report` step, which declares no `output` | accepted; `aggregate` steps may produce prose, and no declaration means no scoring for that step |

### R3.11 — a step's input may name the converted kind it reads, and bare `documents` means `markdown`

R8.4's fourth counter-example says which kind a stage reads is a pipeline
question rather than a conversion one, and leaves it there. Nothing in this spec
picked it up, so `page_images` has been a fully keyed, counted and invalidatable
artifact that **no step can name**: `ConvertReport.text` keeps the `markdown`
kind and silently drops the rest.

The kind is written after the source keyword, separated by `@`:

```yaml
steps:
  - id: describe
    input: documents@page_images
  - id: extract
    input: [documents, describe]        # documents means documents@markdown
```

`@` rather than `:` or `.`: `:` already separates a provider from a model
(spec 009) and a bare `.` reads as an attribute of something. `@` is used
elsewhere in this project to mean "qualified by" — `hf:Qwen/Qwen2.5-7B@1c0f8e6b`
— and that is what it means here.

Bare `documents` keeps meaning what it always meant, so every pipeline in
existence is unaffected. Only `documents` and `reference` take a kind: a step id
names another step's output, which is not a conversion and has no kind to pick.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.pipeline.split_kind`)
- **Proved by:** `tests/unit/test_R003_11__an_input_may_name_the_kind_it_reads.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `describe` declaring `input: documents@page_images` | reads the `page_images` artifacts of every source in `sources` |
| 2 | `extract` declaring `input: documents` | reads the `markdown` artifacts, exactly as it did before this rule existed |
| 3 | `verify` declaring `input: [documents@page_images, reference]` | the first is `page_images` from `sources`, the second `markdown` from `reference`; a kind is per input, not per step |
| 4 | `report` declaring `input: describe@page_images` | load-time error naming the step; a step's output is not a conversion and has no kind to choose |
| 5 | *counter-example* — `documents@markdown` written out in full | accepted and identical to `documents`; the default is a default, not a prohibition |

### R3.12 — a `per_part` step calls the model once per part of its input, and a later step reads them joined in part order

`per_file` is one call per document and `aggregate` is one call over all of them.
A conversion that produces several parts (R8.11) fits neither: a forty-page
container handed to one call is one enormous prompt whose failure loses forty
pages, and handed to `aggregate` it is every page of every document at once.

`per_part` is the third: one call per part, keyed per part, retried per part,
and cached per part. A page that fails costs one page.

What a *later* step reads is the parts joined in part order, one value per
document, each wrapped in a tag naming the part it came from -- the same shape
`aggregate` already uses for documents (spec 003, "Prompt files"), and for the
same reason: a model asked to attribute a finding needs to know which page it
read it on.

```yaml
steps:
  - id: describe
    prompt: prompts/00_describe.md
    input: documents@page_images
    mode: per_part
  - id: extract
    prompt: prompts/01_extract.md
    input: [documents, describe]
    mode: per_file
    output: schemas/incident.yaml
```

A step whose input has no parts -- ordinary converted text -- may not declare
`per_part`. There is nothing to fan out over, and the honest reading of the
request is that its author expected an input this pipeline does not produce.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.pipeline`, `dossier.domain.resolution`)
- **Proved by:** `tests/acceptance/test_R003_12__a_describe_step_reads_one_page_at_a_time.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `describe` reading `documents@page_images`, `INC-4830` holding three pages | three model calls for that document, three keys, three artifacts |
| 2 | one of those three calls failing after its retry | the other two are kept and named; a page that fails costs one page (R6.9's shape) |
| 3 | `extract` declaring `input: [documents, describe]` | `{{describe}}` holds the three descriptions in part order, each wrapped in a tag naming its part |
| 4 | a second run with nothing changed | zero model calls; every part is served from its own cache entry (R5.5) |
| 5 | *counter-example* — a `per_part` step whose input is `documents` | load-time error naming the step; converted text has no parts to fan out over, and running it once would answer a question nobody asked |

### R3.13 — every input value names the document it came from, in `per_file` and `per_part` as well as `aggregate`

An `aggregate` step's inputs have been wrapped in `<document key="…">` since this
spec was written, for a reason stated a few lines above the wrapping: *a model
asked to attribute a finding needs to know which document it read it in, and
`source.document` must name one of them for the field to be grounded (R6.4).* A
`per_file` step was handed the bare text. The reason applies identically, and the
asymmetry was never argued for -- it was what one branch of `_input_values`
happened to do.

The consequence is exact, and playground exercise 05 ran into it the first time a
real model was pointed at it. R6.3 requires `source.document` to name an input to
the stage. The document key was in no part of the prompt. So the model read the
key off the note's own heading, answered `PLAY-1001` for a document whose key is
`PLAY-1001.md`, and every one of its sixteen values -- all sixteen correct
against gold -- was scored `invalid`. The run was asked for a fact it was never
given and marked wrong for not guessing it.

The form is the one `aggregate` already uses, so there is one wrapper in the
system and not two:

```markdown
<source_document><document key="PLAY-1001.md">…</document></source_document>
```

Every input is wrapped, not only `documents`. A step reading an earlier step's
output cites evidence too, and a citation needs a key whatever produced the text
it is citing. A `per_part` step's text inputs are wrapped for the same reason;
its *parts* are pictures and carry no text to wrap, and R3.12's part tags are
unchanged.

**This invalidates every stage key a `per_file` or `per_part` step ever wrote.**
The value handed to a prompt is hashed into that stage's key (spec 005), so
changing the value changes the key -- which is R0.5 working, not a defect in it:
the question changed, so the key changed. A replay recomposes its keys from the
inputs rather than reading them from the manifest (R4.14), so a run written
before this rule cannot be reproduced after it, and `dossier eval`, which scores
a reproduction, cannot score one. Those runs are re-run, not recovered. The
alternative -- rendering one way and keying the other -- would let a workspace
serve an answer produced from a question nobody asked again, which is the exact
thing R0.5 exists to prevent.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R003_13__every_input_value_names_its_document.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract` in `per_file` mode over `PLAY-1001.md`, input `documents` | `{{documents}}` holds `<document key="PLAY-1001.md">…</document>`, the note's text inside it |
| 2 | the model answering `source.document: "PLAY-1001.md"` for that call | grounded, and scorable (R6.3); the key it was asked to carry is a key it was shown |
| 3 | `verify` in `per_file` mode declaring `input: [documents, extract]` | both values wrapped, each naming `PLAY-1001.md`; an earlier step's output is cited like any other evidence |
| 4 | the same pipeline run against a workspace holding entries written before this rule | every document a cache miss; the value hashed into the key is not the value that was hashed before (spec 005) |
| 5 | a run written before this rule, replayed after it | `cannot be reproduced`, naming the entry; a replay recomposes its keys and these are keys no run wrote (R4.14, R4.7) |
| 6 | *counter-example* — an `aggregate` step | unchanged; it already wrapped each document, and this rule is that branch's shape reaching the other two |
| 7 | *counter-example* — the image parts of a `per_part` step | unchanged; a picture carries no text to wrap, and its key already holds the part's bytes (R3.12, R4.14) |

### R3.14 — a step may name its own `model`, and is asked with it; a step that names none is asked with the pipeline's

A pipeline named one model for every step. The common real shape is a cheap
model to extract and a strong one to verify or report, and the only way to get
it was two pipelines. `model:` on a step overrides the pipeline's for that step
alone.

It is held at load time to what the pipeline's is held to: pinned (R3.4, R0.6),
and provided by an installed package (R9.1), with the error naming the step's
key. The pipeline's `model:` stays required. It is the default, and it is what
judges an eval and a calibration (spec 007), whatever the steps name.

The manifest records a step's own model only where it differs from the
pipeline's. So a pipeline that names none -- every pipeline written before this
rule -- resolves to the same manifest byte for byte, and a step naming the
pipeline's own model is the same step as one naming none. `--plan` compares
each step's model with the one it ran with, and names a step's own model beneath
its line; `--replay` rebuilds each step's key with the model it recorded (R4.12,
R4.7).

A client is built for a model at the first cache miss of a step asked with it,
and never before (R9.2 row 5). Each is reached where its own provider is (R9.2)
and checked before its own first call (R9.4, R9.6).

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`), domain (`dossier.domain.resolution`, `dossier.domain.plan`), application (`dossier.application.run`), cli (`dossier.cli.run`, `dossier.cli.eval`)
- **Proved by:** `tests/acceptance/test_R003_14__a_step_is_asked_with_its_own_model.py`, `tests/unit/test_R003_14__which_model_a_step_is_asked_with.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `model: anthropic:claude-sonnet-4-5-20250929`, `extract` naming `model: ollama:qwen2.5:7b@sha256:7f3c29a1` and `verify` naming none; three documents, nothing cached | `extract` asked through the `ollama` provider three times and `verify` through `anthropic` three times; each artifact's provenance record names the model that answered it |
| 2 | that run's manifest | `extract` carries `"model": "ollama:qwen2.5:7b@sha256:7f3c29a1"`, `verify` carries no `model`, and the plan's `model` is the pipeline's |
| 3 | the same run again | every step served from cache, and no client built for either model (R9.2 row 5) |
| 4 | `extract`'s model then changed to `hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b`, and `dossier run incident-audit --plan` | `! extract: model changed` with `model: hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b` beneath it, and `! verify: upstream changed` |
| 5 | instead, the pipeline's `model:` changed to `openai:gpt-4o-2024-08-06`, `extract` still naming its own, and `--plan` | `extract: cached`, and `! verify: model changed` |
| 6 | `dossier run --replay runs/<run_id>/` of row 1's run | reproduced byte for byte and no model asked (R4.7): each key rebuilt with the model its step recorded |
| 7 | `verify` naming `model: anthropic:claude-sonnet-4-5-20250929`, the pipeline's own | the same manifest and the same keys, byte for byte, as naming none |
| 8 | *counter-example* — a pipeline no step of which names a model | no step in its manifest carries `model`, and every key is the one R5.3 composed: nothing written before this rule moves |
| 9 | *counter-example* — `extract` naming `model: anthropic:claude-sonnet-4-5` | load-time error naming `pipeline.yaml`, the line, `steps.0.model` and the alias (R3.4); nothing asked |
| 10 | *counter-example* — `extract` naming `model: mistral:mistral-large-2411`, which no installed package provides | load-time error naming the providers available (R9.1) |
| 11 | *counter-example* — `dossier eval` and `dossier calibrate` over row 1's pipeline | the judge is the pipeline's `model:`; a step's own model answers that step and judges nothing (spec 007) |

### R3.15 — a `per_group` step asks the model once per group, and a document's group is its key up to the first `/`

`per_file` asks about one document and `aggregate` about all of them. A supplier
contract is neither. It is a master agreement and its amendments: the renewal date
is in amendment 3 and the liability cap is in the master
(`docs/second-use-case.md`, finding 1). No single file answers the question, and
one call over every contract is the enormous call R5.10 and R7.2 exist to avoid.

`per_group` is the fourth mode. A document's group is its key up to the first `/`,
and a key with no `/` is a group of one, named by the key itself. No configuration
says so, because every connector already keys a file under what it belongs to: a
Jira attachment is `INC-4821/report.pdf` (R1.6), a Confluence file is
`81920114/escalation-matrix.png` (R1.18), and a folder's file is its path under
the folder, so a contract kept in its own subfolder is `ACME-2024/amendment-3.pdf`.
It is the first segment, not the last directory, so
`ACME-2024/amendments/amendment-3.pdf` is still `ACME-2024`. Keys are unique across
a pipeline's sources (R4.10), so a group may take members from more than one: a
postmortem dropped in a folder under `INC-4821/` joins the Jira issue `INC-4821`.

A group's call holds what an `aggregate` call holds, limited to the group's
documents: each wrapped under its own key, in key order (R3.13). Its artifact is filed under the group's name,
`extract/ACME-2024.json`, and `dossier` writes that name as the artifact's
`document`, as it writes a document's key for `per_file` (R5.10 row 5).
Everything a `per_file` step does per document, a `per_group` step does per group:
the key (R5.14), the cache entry, the retry and the failure (R6.2, R6.9), the trace
(R11.1), and what `--concurrency` counts (R9.19).

A flat folder is a folder of groups of one, and on it `per_group` asks exactly
what `per_file` asks. Contracts named by convention in one folder,
`ACME-2024-master.pdf` beside `ACME-2024-amendment-3.pdf`, are sorted into
subfolders first (see "Existing options considered").

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.groups.group_of`), application (`dossier.application.run`)
- **Proved by:** `tests/acceptance/test_R003_15__a_per_group_step_asks_once_per_group.py`, `tests/unit/test_R003_15__a_documents_group_is_its_key_up_to_the_first_slash.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `ACME-2024/master.pdf`, `ACME-2024/amendment-1.pdf`, `ACME-2024/amendment-3.pdf` and `GLOBEX-2023/master.pdf`, `extract` in `per_group` mode | two model calls; `extract/ACME-2024.json` and `extract/GLOBEX-2023.json`, each naming its group as `document`; `extract: 2 group(s) · 0 from cache · 0 failed` |
| 2 | `ACME-2024`'s call | `{{documents}}` holds three `<document key="…">` blocks -- `ACME-2024/amendment-1.pdf`, `ACME-2024/amendment-3.pdf`, `ACME-2024/master.pdf`, in that order -- and no `GLOBEX-2023` document |
| 3 | `INC-4821` and its attachment `INC-4821/report.pdf`, from `incidents-jira` | one group, `INC-4821`, holding both |
| 4 | `INC-4821` from `incidents-jira`, and `INC-4821/postmortem.pdf` from `incidents-manual` | one group of two, across two sources: a group is a prefix of keys, and keys are unique across sources (R4.10) |
| 5 | `ACME-2024/amendments/amendment-3.pdf` | group `ACME-2024`: the first segment, not the last directory |
| 6 | `GLOBEX-2023`'s answer fails validation twice | that group fails alone -- `extract: 2 group(s) · 0 from cache · 1 failed` -- and `extract/ACME-2024.json` is written (R6.9) |
| 7 | the same run, tracked | one trace per group, named for it, holding each member's key among its inputs (R11.1) |
| 8 | *counter-example* — `PLAY-1001.md`, a key with no `/`, in a flat folder | a group of one, `PLAY-1001.md`: on a flat folder, `per_group` asks exactly what `per_file` asks |
| 9 | *counter-example* — `81920114.pdf`, a page's PDF export (R1.19) | its own group, not page `81920114`'s: its key has no `/` (open question 1) |
| 10 | *counter-example* — the same four documents, `extract` in `per_file` mode | four calls, as before: grouping is a step's choice, and a step that does not make it is unchanged |

### R3.16 — a step that reads a `per_group` step's output is `per_group` or `aggregate`, and anything else is refused at load time

A `per_group` step answers once per group, so its outputs are named for groups. A
`per_file` step reading them would be asked about `ACME-2024/master.pdf` and
handed either the group's answer, which is about three documents, or none, which
drops the evidence. Neither is right, so it is refused when the pipeline loads, as
a `per_part` step over text is (R3.12 row 5). The other direction is sound: a
`per_group` step reading a `per_file` step's outputs gets each member's, under the
member's key, as it gets each member's text.

What a reader admitted by this rule is handed is part of the rule, and not only
that it is admitted: rows 1, 2 and 4 say what each call holds. Proved only at
load time, the rule was MET while every `per_group` or `aggregate` reader of a
group step was handed an empty `{{extract}}`, because the answers were looked up
under the members' keys and a group step files them under the group's.
Playground exercise 16 found it live, in an input hash that was the SHA-256 of
nothing.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.pipeline`, `dossier.domain.groups.filed_under`) plus application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R003_16__only_a_group_or_aggregate_step_reads_a_group_step.py`, `tests/unit/test_R003_16__a_step_reading_a_group_step_is_handed_its_answers.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `verify` in `per_group` mode, `input: [documents, extract]`, `extract` in `per_group` mode | accepted; `ACME-2024`'s call holds its three documents and `extract/ACME-2024.json` |
| 2 | `report` in `aggregate` mode, `input: verify` | accepted; it reads every group's answer, each under its group's name |
| 3 | `verify` in `per_file` mode, `input: [documents, extract]`, `extract` in `per_group` mode | a load-time error naming both steps and both modes, before any work |
| 4 | *counter-example* — `combine` in `per_group` mode reading `extract` in `per_file` mode | accepted; each group's call holds its members' answers, each under the member's key |

### R3.17 — a `reference` document is context and is never audited: no step is asked about it, and nothing is filed under its key

`reference:` names the sources a pipeline reads as context, not the documents it
audits. The example at the top of this spec verifies incidents against an
escalation procedure. Until this rule the run put reference documents in with
the audited ones. A `per_file` step was asked about `OPS-114` as though it were an
incident, and filed `extract/OPS-114.json`. An `aggregate` step's `{{documents}}`
held the procedures among the incidents. A procedure has no loss amount, so each
of those calls answered a question nobody asked. Each was paid for, and no gold
answer could ever score it.

The audited documents are the documents of `sources:`, and a step fans out over
them alone: per document, per part or per group. A source listed under both
`sources:` and `reference:` is read both ways. R4.10 row 4 already allows that
listing.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run.execute`), cli (`dossier.cli.run.run`)
- **Proved by:** `tests/unit/test_R003_17__a_reference_document_is_never_audited.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `sources: [incidents-jira]` holding `INC-4821` and `INC-4822`, `reference: [procedures-confluence]` holding `OPS-114`, `extract` in `per_file` mode over `documents` | two model calls; `extract/INC-4821.json` and `extract/INC-4822.json`, no `extract/OPS-114.json`; `extract: 2 document(s)` |
| 2 | `report` in `aggregate` mode over `documents` | `{{documents}}` holds `INC-4821` and `INC-4822`, and not `OPS-114` |
| 3 | `extract` in `per_group` mode | groups `INC-4821` and `INC-4822`; `OPS-114` is in no group |
| 4 | *counter-example* — one source listed under both `sources:` and `reference:` | its documents are audited, and are reference documents as well |

### R3.18 — `{{reference}}` holds every reference document, each under its own key in key order, whatever the step's mode

Context is the same for every document it is context for. `OPS-114`, the
escalation procedure, applies to `INC-4821` and `INC-4822` alike. So every
`verify` call is shown all of `reference`, each document wrapped as R3.13 wraps
any input, in key order as an `aggregate` step's documents are.

Until this rule, `{{reference}}` was filled from the same per-document text as
`{{documents}}`. In a `per_file` call it held the incident a second time, under
the incident's key. No procedure reached any call, so a prompt that said
"check this against the procedure" was answered without one.

A step that reads `reference` in a pipeline that declares no `reference:` would
be shown nothing. Its prompt would still call that nothing the context. So it is
refused when the pipeline loads, as a step reading a kind nothing makes is
refused (R4.13). R3.3 row 4 still holds: `reference` is a source keyword, and
reading it in a pipeline that declares reference sources is ordinary.

Every reference document goes into every call, and a large reference set is paid
for once per audited document. That is the price of context the model is really
shown. Narrowing it, per group or per step, is not this rule.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`), domain (`dossier.domain.pipeline.validate_references`)
- **Proved by:** `tests/acceptance/test_R003_18__every_call_is_shown_every_reference_document.py`, `tests/unit/test_R003_18__reading_reference_needs_a_reference_source.py`, `tests/unit/test_R003_18__reference_holds_every_reference_document.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `verify` in `per_file` mode over `INC-4821`, `input: [documents, extract, reference]`, reference `OPS-114`, `OPS-115` and `OPS-116` | `{{reference}}` holds `<document key="OPS-114">`, then `OPS-115`, then `OPS-116`, each with its converted text |
| 2 | the call for `INC-4822` | the same `{{reference}}` value, byte for byte |
| 3 | `report` in `aggregate` mode, `input: [verify, reference]` | the same three documents, once, in its one call |
| 4 | a step reading `reference` in a pipeline that declares no `reference:` | a load-time error naming the step, before any work |
| 5 | *counter-example* — `extract` with `input: documents` | no reference document anywhere in its prompt |

### R3.19 — a step that reads an `aggregate` step's output is refused at load time, naming both

An `aggregate` step answers once for every document, and its one artifact is
filed under the reserved key `*` (Modes, above). Every reader looks an earlier
step's answers up under a document's key or a group's, and none of them is `*`.
So a step reading an aggregate step was handed nothing, whatever its mode: a
`per_file` reader was never asked, and a `per_group` or `aggregate` reader was
asked about an empty input and cached under the hash of nothing. No rule said an
aggregate step's output could be read, and none refused a pipeline that did.
Found by `/verify` on 2026-09-29, with a scratch pipeline whose report text
never reached the step after it.

It is refused when the pipeline loads, as a `per_file` reader of a `per_group`
step is (R3.16), and through `previous` as well, which names a step by position
(R4.2). Refusing costs nothing today: no pipeline in the repository reads an
aggregate step, and every one that has one ends with it. Handing the aggregate's
answer to its readers was the other choice. It is a capability nobody has asked
for, and this rule can be superseded by it when someone does (decided by
`a.aleks` on 2026-09-29).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.pipeline.validate_modes`)
- **Proved by:** `tests/unit/test_R003_19__no_step_reads_an_aggregate_step.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `report` in `aggregate` mode, `input: extract`, then `summary` in `per_file` mode, `input: report` | a load-time error naming `summary`, `report` and both modes, before any work |
| 2 | `summary` in `aggregate` mode, `input: report` | the same refusal: a second aggregate step is handed nothing too |
| 3 | `summary` in `per_group` mode, `input: previous`, directly after `report` | the same refusal: `previous` is `report` (R4.2) |
| 4 | *counter-example* — `report` in `aggregate` mode, `input: extract`, the last step | accepted, as every pipeline in the repository has it |

## Open questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | A Confluence page's PDF export is keyed `81920114.pdf` (R1.19) and so is a group of its own, apart from page `81920114` and its files. Should they be one group? | OPEN — needs a Confluence audit that wants the page and its export in one call. Kept open on 2026-09-27: grouping by carrier would supersede R3.15 and change group keys for runs that exist |
| 2 | A group can outgrow what a model accepts in one call: a 60-page master and its amendments. It fails like any request that is too long | OPEN — needs a real contract corpus to measure against |
