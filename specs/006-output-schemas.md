# 006 — Structured output, grounding and abstention

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

**R6.1** A stage output that does not validate against its declared schema is
never written and never cached.

**R6.2** Validation failure triggers exactly one retry carrying the validation
error; the retry is recorded in the provenance record.

**R6.3** Every non-null field carries a `source` naming a document that is an
input to that stage.

**R6.4** A `span` that cannot be located in the named document's converted text
marks the field `ungrounded`.

**R6.5** `value: null` with a `reason` is valid output and is never counted as a
failure.

**R6.6** A field may not be simultaneously non-null and missing `source`.

**R6.7** The same pydantic model generates the model-facing schema, the
validation, and the scorer's field list. There is no second definition anywhere.

**R6.8** Schema changes are versioned; the schema hash is part of every affected
cache key (spec 005).

**R6.9** A document that fails after retry does not abort the run and does not
poison the cache for other documents.
