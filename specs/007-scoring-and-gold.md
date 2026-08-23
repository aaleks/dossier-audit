# 007 — Gold sets, scoring and the change gate

## Purpose

Answer the question "is the output correct" with a number, per field, against
answers a human has verified.

## Gold set

`gold/<name>/` holds one file per document:

```json
{
  "document": "INC-4821",
  "verified_by": "a.muster",
  "verified_at": "2026-08-14",
  "fields": {
    "loss_amount":      {"value": 48200.00, "currency": "CHF"},
    "resolution_date":  {"value": "2026-07-28"},
    "severity":         {"value": "major"},
    "root_cause":       {"value": null, "reason": "not stated in document"}
  }
}
```

## Scorers

| Field kind | Scorer | Model needed |
|---|---|---|
| amount, date, reference | exact match after normalisation | no |
| enum (status, severity, category) | allowed-value membership + equality | no |
| evidence span | occurs in source text (spec 006) | no |
| free text (cause, summary) | LLM judge with a written rubric | yes |

Scorers are registered per field type in the schema, not hard-coded per pipeline.

## Reporting

Scores are reported **per field**. A single blended accuracy is never the
headline, because a field at 62% and a field at 99% need different work.

```
52 documents · 9 fields · overall 94.1%
  loss_amount       99.1%
  resolution_date   98.2%
  severity          97.6%
  root_cause        62.4%   <- weakest
```

## Judge calibration

Before a judge is used for reporting, the same sample is scored by a human and by
the judge, and agreement is measured. A judge below the configured agreement
threshold may not be used as a reported metric. Agreement is re-measured whenever
the judge model or its rubric changes.

## The review loop

A run emits `review.jsonl`: one record per field that is empty, ungrounded, low
confidence, or disagrees with the gold set. A reviewer marks each `correct`,
`incorrect`, or supplies the right value. Accepted corrections are merged into
the gold set.

Reviewing is how the gold set grows. There is no separate labelling exercise.

## The change gate

`dossier eval <pipeline> --compare <a> <b>` scores two configurations over the
same gold set and prints the per-field delta. Prompt changes, model changes and
converter changes all pass through it.

## Must hold

**R7.1** Scoring is deterministic for every non-judge field type: the same output
and gold set always produce the same score.

**R7.2** Results are reported per field. An overall figure may be shown, but never
without the per-field breakdown.

**R7.3** A field the gold set records as `null` is scored correct when the run
also abstains, and incorrect when the run supplies a value.

**R7.4** An ungrounded field is scored incorrect even when its value matches gold.

**R7.5** A judge whose measured agreement with human scores is below the
configured threshold cannot be used as a reported metric.

**R7.6** Judge agreement is re-measured whenever the judge model or rubric
changes; a stale calibration is an error, not a warning.

**R7.7** Corrections accepted into the gold set are versioned, attributed and
timestamped.

**R7.8** `--compare` scores both configurations over exactly the same documents
and reports per-field deltas, flagging every regression.

**R7.9** Every run, its per-field scores, its pinned model and its judge
calibration are recorded to MLflow under the pipeline name.

**R7.10** Scoring performs no network I/O for non-judge field types.
