# 006 — Structured output, grounding and abstention

**Status:** Partially implemented
**Rules:** R6.1 – R6.20

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

### What a reader cannot tell apart

A span is what the document says, and a model quoting it reads the document the
way a person does. Some differences between the two are invisible to that reader
and still fail a string search: a PDF text layer spells `certiﬁcate` with a
ligature, a typesetter's apostrophe is `’`, a word breaks across a line as
`certifi-` and `cate`, and a converter writes `**Status:** Done` where the reader
sees `Status: Done`. The model "corrects" each of these when it quotes, and an
honest citation comes back `ungrounded` -- scored incorrect before its value is
looked at (R7.4).

So the span and the document are both *folded* before the search, as whitespace
already was: Unicode compatibility forms (R6.17), typographic quotes and dashes
(R6.18), a hyphen at a line break (R6.19), and the markdown a converter wrote
around words (R6.20). Every fold is applied to both sides, so a span quoted
exactly still grounds, and none of them reaches a letter, a digit or the case of
either: `MAJOR` is still not `major`, and `48,200` is still not `48'200`.

It changes verdicts, and so scores. Grounding is re-derived from a cached answer
on every read rather than stored beside it (R5.5), so no key moves and nothing is
asked of a model again -- a run served from cache, or replayed, is judged by the
folds in force when it is read. A span that was `ungrounded` before them and is
located now was an honest citation all along.


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
| 2 | the same field, checked | not a failure: an abstaining field is for a person to review, which is not the same as failing (spec 007, "The review loop", not built) |
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
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4822` fails `extract` after its retry, and `verify` reads `extract` | `verify` does not run for `INC-4822`: no model call, no artifact, no cache entry |
| 2 | `INC-4821` in the same run, which `extract` handled normally | `verify` runs for it as usual; one document's failure is not the corpus's (R6.9) |
| 3 | the run's report afterwards | names `INC-4822` once, under `extract`, and not a second time under `verify`; a failure list is a list of causes |
| 4 | *counter-example* — an `aggregate` step in the same run | runs, over the documents that did produce output. An aggregate reads a set, and a member that is absent from it is not a missing input |

### R6.14 — `source.page` is derived from the located span, never taken from the model's answer

The field record has carried a `page` since the shape was written, and nothing
has ever checked it. The model asserts a number and no code disagrees, so the
one part of a provenance record an auditor actually navigates by is the one part
nothing verifies — which is worse than omitting it, because it looks checked.

It becomes an output of grounding rather than an input to it. R6.4 already
locates the span by string search; the page is the anchor that search landed
after. A converter that emits no anchors yields `null`, which is the honest
answer for a document that has no pages.

The model is still *shown* a `page` in its schema and still free to answer one.
Removing it would change the generated schema, and with it `d24c86e1` and every
stage key downstream of it (R6.12) — a large blast radius to stop a model
volunteering a number that is now discarded before anything reads it.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.page_of_span`)
- **Proved by:** `tests/unit/test_R006_14__the_page_is_derived_from_the_located_span.py`, `tests/acceptance/test_R006_14__a_run_cites_the_page_the_span_is_on.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | span `total exposure CHF 48'200`, located under page 3's anchor in `INC-4821`'s converted text | `page: 3`; the number is read from the document, not from the answer |
| 2 | the model answering `page: 8` for that same span | `page: 3`; the model's number is discarded rather than compared, so there is no mismatch to report and nothing to disagree about |
| 3 | a span located in a converted markdown note, which carries no anchors | `page: null`; a document with no pages has no page to cite, and a fabricated `1` would be the same lie in a smaller font |
| 4 | a span that cannot be located at all | `ungrounded` (R6.4) and no page; a page for evidence nobody found would be provenance for a claim that has none |
| 5 | *counter-example* — a field with `value: null` and no span | no page and no grounding check; there is no claim to locate (R6.5) |

### R6.15 — a field citing a document the stage was shown as pictures is `described`, not `ungrounded`

R6.4 locates a span by searching the converted text. A stage that read
`documents@page_images` has no converted text to search: the evidence is on a
page the model looked at, and the string it quotes was never a string. Every
field such a stage produces therefore fails the search, and the existing answer
to a failed search is `ungrounded` — "the value may be right, and nothing in the
document shows it" — which is exactly backwards. The document does show it. What
is missing is a text layer, and punishing a field for that scores honest visual
evidence as fabrication (R7.4).

`described` is the third grounding state, beside `grounded` and `ungrounded`. It
is not a failure and it is not a pass: it says the claim was read off a picture
and a string search cannot confirm it, so something else must — which is R7.21's
judge, and why the two states are counted and gated separately rather than
summed.

Better evidence still wins. A stage shown pictures whose span *does* locate in
text the run also holds is `grounded`, not `described`: a model quoting a
document verbatim from its rendering has produced a citation anyone can check,
and demoting it for the route it took would throw that away.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.check_field`)
- **Proved by:** `tests/unit/test_R006_15__a_field_read_off_a_picture_is_described.py`, `tests/acceptance/test_R006_15__a_run_counts_described_fields_apart_from_grounded.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a `root_cause` on `INC-5720`, shown to the step as `page_images`, whose span is in no converted text | `described`; not a failure, and not counted as grounded |
| 2 | the same field on a step shown only `markdown` | `ungrounded` (R6.4); nothing changes for a stage that had text to search |
| 3 | a span that *does* locate in text the run holds, on a step shown pictures | `grounded`; a verbatim citation is checkable however the model came by it |
| 4 | a run whose `extract` step produced one described field | the step's summary line reads `... · 0 failed · 1 described`; a described field is added to neither the grounded count nor the failed one |
| 5 | *counter-example* — a field with `value: null` and a reason, on a step shown pictures | `abstained` (R6.5); there is no claim to describe, and a picture does not make one |
| 6 | *counter-example* — a field citing a document this stage was shown in no kind at all | `invalid` (R6.3); being shown pictures of *one* document does not excuse citing another |

### R6.16 — `dossier run` names every field finding it produced, with the reason the check gave

A document with an ungrounded or invalid field has not failed -- it has findings,
and R6.9 is careful that they do not abort the run. What nothing said is that
they must be *reported*, and so they were not: `DocumentResult.field_failures`
existed, was correct, and had no caller anywhere in `src/`. A run printed
`4 document(s) · 0 from cache · 0 failed` over sixteen fields of which fifteen
were invalid.

The reason is already written. `check_field` returns a `detail` composed for a
person -- `loss_amount: cites 'PLAY-1001', which was not an input to this stage.
Inputs were ['PLAY-1001.md'] (R6.3)` -- and it is the same string R7.4 row 2
requires a score to carry. Printing it costs nothing and is the difference
between a number and a diagnosis.

A finding is not a failure and does not become one here. The exit code is R6.9's
and R0.11's business and is untouched: a run whose every field is ungrounded
still wrote every artifact, and a person who wants a non-zero exit for findings
is asking for a gate this rule does not build.

Counted on the step line beside `described`, which is the same shape for the same
reason -- and, like it, absent when there are none, because `· 0 findings` on
every line of every clean run is noise (R6.15).

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R006_16__a_run_names_its_field_findings.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract` over four notes, every field citing a key with no extension | `extract: 4 document(s) · 0 from cache · 0 failed · 16 findings`, and a line per finding naming its document, its field and the reason |
| 2 | one finding, on `PLAY-1001.md` | `    PLAY-1001.md  loss_amount: cites 'PLAY-1001', which was not an input to this stage. Inputs were ['PLAY-1001.md'] (R6.3)` |
| 3 | the same run's exit code | `0`; a finding is not a failure, and every artifact was written (R6.9, R0.11) |
| 4 | a run with findings on a step served entirely from cache | the same findings, named the same way; grounding is re-derived from the artifact on a hit (R5.5), so a cached run is as diagnosable as a fresh one |
| 5 | *counter-example* — a run whose every field is grounded | no finding lines and no count on the step line; the clean case reads exactly as it did |
| 6 | *counter-example* — a field that abstained with a reason | not a finding; abstention is valid output and is never counted as a failure (R6.5) |
| 7 | *counter-example* — a `described` field | not a finding; it is already counted as `described` on the step line, and it is neither a pass nor a failure (R6.15) |

### R6.17 — a span is compared with its document after Unicode compatibility folding, on both sides

NFKC, the Unicode normalisation whose purpose is this: `ﬁ` is `fi`, a full-width
`Ｃ` is `C`, and an `é` written as `e` plus a combining accent is the `é` a
keyboard types.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.locate_span`)
- **Proved by:** `tests/unit/test_R006_17__unicode_compatibility_forms_are_folded.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4830`'s text reading `the renewed certiﬁcate` (U+FB01), span `the renewed certificate` | grounded |
| 2 | the span with the ligature, the text without it | grounded; both sides are folded |
| 3 | text `Café` as `e` and U+0301, span `Café` precomposed | grounded |
| 4 | *counter-example* — text `major`, span `MAJOR` | `ungrounded`; folding compatibility forms is not folding case |

### R6.18 — typographic quotes, apostrophes and dashes compare equal to their plain forms

`’ ‘ ‛ ′` are `'`; `“ ” „ ‟ ″` are `"`; `‐ ‑ ‒ – — ―` and the minus sign `−` are `-`.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.locate_span`)
- **Proved by:** `tests/unit/test_R006_18__typographic_quotes_and_dashes_are_folded.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821`'s text `total exposure CHF 48’200` (U+2019), span `total exposure CHF 48'200` | grounded |
| 2 | text `the claim was “supported”`, span `the claim was "supported"` | grounded |
| 3 | text `declined 09:12–09:54` (en dash), span `declined 09:12-09:54` | grounded |
| 4 | *counter-example* — text `total exposure CHF 48'200`, span `total exposure CHF 48,200` | `ungrounded`, as R6.4 row 3 says: a comma is not an apostrophe |

### R6.19 — a word broken across a line by a hyphen is found joined or hyphenated, and a soft hyphen is not there

A hyphen that ends a line may be the typesetter's, splitting `certificate`, or
the word's own, in `well-known`. Nothing in the text says which, so the document
is read both ways and a span found in either is located. Its page is the page of
the reading it was found in (R6.14). A soft hyphen (U+00AD) is invisible, and is
dropped.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.locate_span`, `dossier.domain.grounding.page_of_span`)
- **Proved by:** `tests/unit/test_R006_19__a_word_hyphenated_across_a_line_is_found.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | text `the renewed certifi-\ncate was never deployed`, span `the renewed certificate was never deployed` | grounded |
| 2 | text `a well-\nknown gap`, span `a well-known gap` | grounded |
| 3 | text `certi­ficate`, span `certificate` | grounded |
| 4 | row 1's text behind `<!-- page 2 -->`, in a document with three pages | the span's page is `2` |
| 5 | *counter-example* — text `pre- and post-deploy checks`, span `pre and post-deploy checks` | `ungrounded`; that hyphen is not at a line break |

### R6.20 — the markdown a converter wrote around words is not part of the text a span is compared with

Converters write markdown (spec 008): `**Status:** Done` in a Jira issue's note,
bold and links in Docling's. Strong and emphasis markers, strikethrough, inline
code and link syntax are folded to the words they mark. A `*` or `_` that marks
nothing -- inside a word, or unpaired -- is text, as CommonMark reads it.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.grounding.locate_span`)
- **Proved by:** `tests/unit/test_R006_20__markdown_around_words_is_folded.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821`'s note `**Status:** Done`, span `Status: Done` | grounded |
| 2 | the same note, span `**Status:** Done` | grounded; a model that kept the markers is folded the same way |
| 3 | text `see [the rollback](https://git.example/r/77)`, span `see the rollback` | grounded |
| 4 | text ``the `payments-db` pool``, span `the payments-db pool` | grounded |
| 5 | text `the *renewed* certificate`, span `the renewed certificate` | grounded |
| 6 | *counter-example* — text `pool lb_acq_01 held 3*2 connections`, span `pool lbacq01 held 32 connections` | `ungrounded`; `_` inside a word and a lone `*` are text, not emphasis |
