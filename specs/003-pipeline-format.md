# 003 — Configuration format

**Status:** Implemented
**Rules:** R3.1 – R3.13

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
    space: OPS
    label: procedure
    export: pdf
    convert: [markdown, page_images]
```

`fields` doubles as the normalisation projection for hashing (spec 002). It is
**optional**, and its absence is meaningful rather than a default: a source with
no `fields` has its payload hashed exactly as received (R2.10). That is why the
folder source above declares none — every byte of a dropped file counts.

An empty list is not the same thing and is rejected: `fields: []` is a projection
onto nothing, which no payload satisfies.

The keys every source takes are `id`, `type`, `fields`, `convert` and
`watermark_overlap`. Anything else -- `path`, `query`, `space` -- belongs to the
source's type, and its connector declares it; the loader checks a source against
both before anything runs (R1.10).

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
| `reference` | Converted documents from `reference` |
| `<step id>` | That step's outputs |
| `previous` | The immediately preceding step (sugar — see spec 004) |
| `previous(n)` | The preceding `n` steps (sugar — see spec 004) |

### Modes

- `per_file` — one model call per document; output is one artifact per document.
- `aggregate` — one model call over all inputs; output is a single artifact.

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
