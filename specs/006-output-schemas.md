# 006 — Structured output, grounding and abstention

**Status:** Partially implemented
**Rules:** R6.1 – R6.13

## Purpose

Guarantee that a stage's output is well-formed, that every extracted value points
at the evidence it came from, and that "not stated" is expressible.

## Field record

Every extracted field is emitted in this shape:

```json
{
  "field": "loss_amount",
  "value": 48200.00,
  "currency": "CHF",
  "source": {
    "document": "INC-4821",
    "page": 3,
    "span": "total exposure CHF 48'200"
  },
  "confidence": "high"
}
```

Abstention is a first-class answer:

```json
{
  "field": "root_cause",
  "value": null,
  "reason": "not stated in document",
  "confidence": "none"
}
```

## Obtaining valid output

1. A JSON Schema is generated from the step's field declaration (R6.10) and
   passed to the model as a structured-output or tool specification.
2. The response is validated against that same generated schema.
3. On validation failure, the call is retried **once**, with the validation error
   appended to the prompt.
4. A second failure is a stage error for that document. The run continues; the
   document is reported as failed and is not cached.

## The span check

`source.span` must occur in the converted text of the named document, after
whitespace normalisation. This is a string search, not a judgement, and it costs
nothing.

A field whose span cannot be located is marked `ungrounded` and treated as a
failure of that field — regardless of how plausible the value looks.

## Must hold

### R6.1 — output that does not validate against its schema is never written and never cached

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R006_1__invalid_output_is_never_written.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the model returns `{"loss_amount": "quite a lot"}` against a numeric field, twice | no artifact on disk, no cache entry, the document reported as failed |
| 2 | the model returns valid JSON with an unknown extra field | rejected; the schema is closed, and a field nobody declared is a silent contract change |
| 3 | the model returns prose rather than JSON | rejected at parse, and counted as a validation failure for retry purposes (R6.2) |
| 4 | *counter-example* — output where `root_cause` is `null` with a reason | valid, written and cached; abstention is a conforming answer (R6.5) |

### R6.2 — validation failure triggers exactly one retry, carrying the error, and the retry is recorded

One retry, because a model that cannot produce the shape twice will not produce
it on the fifth attempt either, and an unbounded retry loop turns a bad prompt
into a bill.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R006_2__validation_failure_retries_exactly_once.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | first response invalid, second valid | exactly two model calls; the artifact is written; its record notes one retry |
| 2 | both responses invalid | exactly two model calls, not three; the document is reported as failed |
| 3 | the retry prompt | contains the validation error text from the first failure |
| 4 | *counter-example* — a transport timeout rather than a validation failure | not a validation retry; it is a stage error and is not counted against this budget |

### R6.3 — every non-null field carries a source naming a document that is an input to that stage

A citation to a document the stage never read is worse than no citation, because
it looks checkable.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.check_source`)
- **Proved by:** `tests/unit/test_R006_3__source_must_name_an_input_document.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `loss_amount` on `INC-4821`, a `documents` input of `verify` | accepted |
| 2 | `loss_amount` citing `INC-9999`, not an input of that stage | rejected; the field is invalid, not merely ungrounded |
| 3 | `loss_amount` citing `OPS-114`, a `reference` input of `verify` | accepted; reference documents are inputs |
| 4 | *counter-example* — `root_cause` with `value: null` | no `source` required; there is nothing to evidence (R6.5) |

### R6.4 — a span that cannot be located in the named document marks the field ungrounded

After whitespace normalisation, and by string search alone. No judgement, no
model, no cost.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.locate_span`)
- **Proved by:** `tests/unit/test_R006_4__unlocatable_span_marks_field_ungrounded.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | span `total exposure CHF 48'200`, present in the converted text of `INC-4821` | grounded |
| 2 | the same span with a doubled internal space, converted text with one | grounded; whitespace is normalised on both sides before searching |
| 3 | span `total exposure CHF 48,200`, not present in the text | `ungrounded`, even though the value `48200.00` is correct (R7.4) |
| 4 | *counter-example* — a field with `value: null` and no span | not ungrounded; there is no claim to ground |

### R6.5 — `value: null` with a reason is valid output and is never counted as a failure

"Not stated" is an answer. A system that cannot say it will invent something
instead.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.check_field`)
- **Proved by:** `tests/unit/test_R006_5__abstention_is_valid_output.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause` null with `reason: not stated in document` | valid; written and cached |
| 2 | the same field in `review.jsonl` | listed for human review, which is not the same as failing (R7.x review loop) |
| 3 | `root_cause` null with no `reason` | invalid; abstention must say why it abstained |
| 4 | *counter-example* — `loss_amount` null when the gold set records `48200.00` | valid output, and scored incorrect; validity and correctness are different questions (R7.3) |

### R6.6 — a field may not be both non-null and missing a source

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.check_field`)
- **Proved by:** `tests/unit/test_R006_6__non_null_without_source_is_invalid.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `severity: major` with no `source` | invalid |
| 2 | `severity: major` with a `source` whose `span` is empty | invalid; an empty span cannot be located and cannot be checked |
| 3 | `loss_amount: 0.00` with a source | valid; zero is a value, not an absence |
| 4 | *counter-example* — `root_cause` null with a reason and no source | valid (R6.5) |

### R6.7 — one pydantic model generates the model-facing schema, the validation and the scorer field list

There is no second definition anywhere. Two definitions of one schema disagree
eventually, and the disagreement shows up as a scoring bug months later.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.schemas`)
- **Proved by:** `tests/unit/test_R006_10__fields_are_declared_once_in_yaml.py`
- **Status:** SUPERSEDED by R6.10

| # | Given | Then |
|---|-------|------|
| 1 | a field added to the incident model | it appears in the model-facing JSON schema, in validation, and in the scorer field list, with no other edit |
| 2 | the scorer field list compared against the model's fields | equal sets; neither has an entry the other lacks |
| 3 | the JSON schema sent to the model | generated from the model, not stored as a second hand-written copy |
| 4 | *counter-example* — a per-field scorer *choice*, such as exact-match versus judge | declared on the field in the model; it is configuration of one definition, not a second definition (R7.x scorers) |

### R6.8 — schema changes are versioned and the schema hash is part of every affected key

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R006_11__field_declaration_hash_is_part_of_affected_keys.py`
- **Status:** SUPERSEDED by R6.11

| # | Given | Then |
|---|-------|------|
| 1 | `schemas/incident.json` edited, hash moving from `b81f0c6d` | the `extract` and `verify` keys change; `report`'s changes through its inputs |
| 2 | the same | conversions are unchanged; a schema does not affect converting a document (R5.4) |
| 3 | a schema edited in a way that changes no field, such as a description | the key still changes; the schema is hashed as bytes |
| 4 | *counter-example* — a schema file present in the repository but referenced by no step | its hash is in no key; only schemas a step declares are part of anything |

### R6.9 — a document that fails after retry does not abort the run and does not poison other documents

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R006_9__document_failure_is_isolated.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4822` fails validation twice, in a run of 21 documents | the other 20 complete and are cached |
| 2 | the same | the run reports one failed document and exits non-zero |
| 3 | the same, re-run after the prompt is fixed | the 20 are served from cache; only `INC-4822` is recomputed (R5.7) |
| 4 | *counter-example* — a resolution error before any stage runs | aborts everything; resolution failures are total, per-document failures are not (R4.1) |

## Declaring the fields a step extracts

A step's `output` names a **field declaration**: one YAML file listing the fields
being extracted and what kind of answer each holds.

```yaml
# pipelines/incident-audit/schemas/incident.yaml
fields:
  loss_amount:     {kind: amount, currency: CHF}
  resolution_date: {kind: date}
  severity:        {kind: enum, values: [minor, major, critical]}
  affected_systems: {kind: reference}
  root_cause:      {kind: free_text, judge: rubrics/root_cause.md}
```

Five kinds, and the kind is what picks the scorer (spec 007):

| `kind` | Compared by | Needs a model |
|---|---|---|
| `amount` | the number, after normalising separators and currency | no |
| `date` | the date, in unambiguous forms only | no |
| `enum` | membership in `values`, case folded | no |
| `reference` | text, case folded | no |
| `free_text` | a judge against the named rubric | yes |

Two things are generated from that one file and never written by hand: the JSON
Schema shown to the model, and the field list a scorer works from. That is what
"there is no second definition" now means — the guarantee R6.7 was protecting,
kept, with the authoring language changed.

### Why YAML and not a Python model

R6.7 required a pydantic model. It was superseded because of who reads a
pipeline. The people this tool exists for are the ones checking whether a
finding is defensible, and under a Python declaration the file that says *what
correct means* is the one they cannot read. Everything else a pipeline author
writes — `sources.yaml`, `pipeline.yaml`, the prompts — is already a document.

It also means `dossier` never imports an author's module to discover their
fields. A pipeline stays inert data: opening someone else's runs nothing.

The cost is real and small. `dossier` generates the JSON Schema itself rather
than getting it from pydantic, and a field declaration is validated by `dossier`
rather than by pydantic's own loader.

## Must hold — added

### R6.10 — a step's fields are declared once, in YAML, and everything else is generated

The declaration is the only place a field's name and kind are written. The JSON
Schema shown to the model and the field list a scorer works from are both
derived from it, so neither can disagree with it or with the other.

Supersedes R6.7, which required the one definition to be a pydantic model. The
guarantee is unchanged and the authoring language is not: see "Why YAML and not
a Python model" above.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.fields`)
- **Proved by:** `tests/unit/test_R006_10__fields_are_declared_once_in_yaml.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a field added to `incident.yaml` | it appears in the generated JSON Schema and in the scorer field list, with no other edit |
| 2 | the scorer field list compared against the declaration | equal sets; neither has an entry the other lacks |
| 3 | the JSON Schema sent to the model | generated at load time, never read from a committed file |
| 4 | a field declaring `kind: enum` with no `values` | load-time error naming the field; an enum with no vocabulary can match nothing |
| 5 | a field declaring `kind: free_text` with no `judge` | load-time error; free text is scored by a judge against a rubric, and there is no default rubric to fall back on (spec 007, "Scorers") |
| 6 | *counter-example* — a field's scorer *choice*, `amount` versus `free_text` | configuration of the one declaration, not a second definition; that is what `kind` is |

### R6.11 — a step's field declaration is part of every key that step's output depends on

Supersedes R6.8, which put the hash of a hand-written JSON Schema into the key.
Under R6.10 the file a step's `output` names is a YAML field declaration and the
JSON Schema is generated from it, so the declaration is what is hashed. It fills
the `schema_hash` slot of the stage key (spec 005) and is hashed the way spec 005
hashes every configuration file: decoded text, line endings normalised, never
interpreted. R6.8's word "versioned" had no example and nothing to test beyond
the hash, and is not carried over.

**Closed by R6.12.** The generated JSON Schema is produced by `dossier`'s own
code, so a change to that generator can change what the model is shown without
one byte of the declaration moving. R0.5 says that must move a key; R6.12 hashes
the generated schema as well, rather than keying a generator version.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R006_11__field_declaration_hash_is_part_of_affected_keys.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `schemas/incident.yaml` edited, hash moving from `6e0d4b27` | the `extract` and `verify` keys change; `report`'s changes through its inputs |
| 2 | the same | conversions are unchanged; a field declaration does not affect converting a document (R5.4) |
| 3 | `incident.yaml` edited where the generated JSON Schema cannot see it, such as the rubric path `root_cause` names as its `judge` | the key still changes; the declaration is hashed as text, not as what is generated from it |
| 4 | *counter-example* — a field declaration present in the pipeline directory but named by no step's `output` | its hash is in no key; only declarations a step names are part of anything |

### R6.12 — the schema the model is shown is part of every key its step's output depends on

Closes R6.11's open question. R6.11 keys the declaration's text, and the JSON
Schema shown to the model is generated from it by `dossier`'s own code -- so a
change to that code, a property added to the record model or a library that
renders the schema differently, changes what the model is asked with no byte of
the declaration moving. R0.5 says that must move a key.

The generated schema is hashed alongside the declaration rather than replaced by
a generator version: a version someone has to remember to raise is a key that
stays still on exactly the change nobody thought mattered. It is hashed as
canonical JSON -- sorted keys, no insignificant whitespace, UTF-8 -- so the same
schema gives the same bytes on every machine (R5.6), and it appears in the
provenance record as well as the key (R5.1).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R006_12__generated_schema_is_part_of_affected_keys.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a property added to the field record model, `incident.yaml` unchanged at `6e0d4b27` | the `extract` and `verify` keys change; the model is shown a different schema |
| 2 | the same generated schema with its keys built in a different order | the same key; the schema is hashed as canonical JSON, not as a dict happened to be built |
| 3 | only the rubric `root_cause` names as its `judge` edited | the key changes through the declaration's hash (R6.11 row 3), while the generated schema's hash does not |
| 4 | *counter-example* — the `report` step, which declares no `output` | no generated schema and nothing in either schema slot; its key moves only through its inputs (R6.11 row 1) |

### R6.13 — a step does not run for a document an earlier step produced nothing for

R6.9 says a failed document does not stop the run. This says what the steps
above it do about that document: nothing.

The alternative is what the code did before this rule existed — hand the step an
empty string for the missing input and carry on. That asks a model about a
document nobody read, pays for the call, and caches an answer under a key whose
input hash is the hash of `""`, so the emptiness is invisible in the provenance
record and the answer is served again on the next run (R5.5). It also reports the
same document failing twice for one cause, which is how a run's failure list
stops being a list of causes.

Skipping is not failing. The document already failed, once, at the step that
could not produce its output; the steps above it have nothing to add.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run`)
- **Proved by:** `tests/unit/test_R006_13__a_step_skips_a_document_with_no_upstream_output.py`
- **Status:** IN PROGRESS

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4822` fails `extract` after its retry, and `verify` reads `extract` | `verify` does not run for `INC-4822`: no model call, no artifact, no cache entry |
| 2 | `INC-4821` in the same run, which `extract` handled normally | `verify` runs for it as usual; one document's failure is not the corpus's (R6.9) |
| 3 | the run's report afterwards | names `INC-4822` once, under `extract`, and not a second time under `verify`; a failure list is a list of causes |
| 4 | *counter-example* — an `aggregate` step in the same run | runs, over the documents that did produce output. An aggregate reads a set, and a member that is absent from it is not a missing input |
