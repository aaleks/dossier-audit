# 003 — Configuration format

Two files. Both are validated against pydantic models at load time; an invalid
file is a hard error before any work begins.

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

`fields` doubles as the normalisation projection for hashing (spec 002).

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
    output: schemas/incident.json

  - id: verify
    prompt: prompts/02_verify.md
    input: [documents, extract, reference]
    mode: per_file
    output: schemas/incident.json

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

## Prompt files

Multiple inputs are injected under distinct labelled tags, never concatenated:

```markdown
<source_document>{{documents}}</source_document>
<extraction>{{extract}}</extraction>
<procedure>{{reference}}</procedure>
```

## Must hold

**R3.1** An unknown key, a missing required key or a wrong type in either file is
a load-time error naming the file, the line and the offending key.

**R3.2** A step `id` is unique within a pipeline and matches `[a-z][a-z0-9_]*`.

**R3.3** A step referencing an id that does not exist, or that appears later in
the list, is a load-time error.

**R3.4** A `model` value that is not fully version-pinned is rejected at load
time (invariant G6).

**R3.5** Every `output` path resolves to a schema file that itself loads and
validates.

**R3.6** Every `{{...}}` placeholder in a prompt corresponds to a declared input
of that step, and every declared input appears in the prompt. Either mismatch is
a load-time error.

**R3.7** A pipeline declaring `gold` must point at a directory that exists and
conforms to spec 007.

**R3.8** Loading a valid configuration performs no network I/O and no model calls.
