# 003 — Configuration format

**Status:** Partially implemented
**Rules:** R3.1 – R3.10

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
    query: project = INC AND type = Incident
    fields: [key, summary, status, created, resolution, description, comments]
    attachments: true
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

In a `per_file` step each placeholder holds one document's text. In an
`aggregate` step the same placeholder holds every document, and each is wrapped
in a tag naming the key it came from:

```markdown
<extraction>
<document key="INC-4821">{...}</document>
<document key="INC-4822">{...}</document>
</extraction>
```

Wrapped rather than concatenated, for the same reason the inputs above are: a
model asked to attribute a finding needs to know which document it read it in,
and `source.document` must name one of them for the field to be grounded (R6.4).
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
- **Status:** NOT MET

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
- **Status:** NOT MET

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

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R003_7__gold_directory_is_validated_at_load_time.py`
- **Status:** NOT MET

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
- **Status:** NOT MET

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
