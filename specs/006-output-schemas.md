# 006 — Structured output, grounding and abstention

**Status:** Partially implemented
**Rules:** R6.1 – R6.9

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

1. The schema is a pydantic model. Its JSON schema is passed to the model as a
   structured-output or tool specification.
2. The response is validated against the same model.
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
- **Proved by:** `tests/unit/test_R006_7__one_model_generates_schema_validation_and_scorers.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a field added to the incident model | it appears in the model-facing JSON schema, in validation, and in the scorer field list, with no other edit |
| 2 | the scorer field list compared against the model's fields | equal sets; neither has an entry the other lacks |
| 3 | the JSON schema sent to the model | generated from the model, not stored as a second hand-written copy |
| 4 | *counter-example* — a per-field scorer *choice*, such as exact-match versus judge | declared on the field in the model; it is configuration of one definition, not a second definition (R7.x scorers) |

### R6.8 — schema changes are versioned and the schema hash is part of every affected key

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R006_8__schema_hash_is_part_of_affected_keys.py`
- **Status:** NOT MET

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
