# 007 — Gold sets, scoring and the change gate

**Status:** Partially implemented
**Rules:** R7.1 – R7.12

## Purpose

Answer the question "is the output correct" with a number, per field, against
answers a human has verified.

This is the only spec containing `evaluated` rules. Everything else in `dossier`
is a decision with an exact answer; the two rules at the end are judgements about
generated text, and they are the exception the design works hard to keep small.

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

The field type is what picks the scorer, and it is stated rather than inferred
from the value: a scorer that sniffed `"48200"` as a number and `"major"` as text
would give the same pair different verdicts depending on what the model happened
to return, which is the opposite of R7.1.

`amount` and `date` are normalised before comparison; `reference` and `enum` are
compared as text with case folded, because which case a model echoed a closed
vocabulary back in is not information.

A value that is not well formed for its type is **not** a mismatch. `13/45/2026`
scored against a `date` is reported as unreadable, not as a disagreement, because
the two need different work and a report that conflated them would send someone
looking for a discrepancy that is not there.

**An ambiguous date is refused rather than resolved.** `07/08/2026` is 7 August in
one country and 8 July in another, and a scorer that picked one would be quietly
wrong for half of every year. `28.07.2026` is unambiguous — no month is 28 — and
is read. `2026-07-28` always is.

Grounding and abstention are decided before the field's type is consulted. Both
are facts rather than judgements: whether a span was locatable, and whether the
run abstained, mean the same thing for a free-text field as for an amount. R7.3's
own examples are all `root_cause`, which is free text — so deferring to a judge
first would leave that rule with nothing it could score, and R7.4 admits no
exception for free text either.

## Reporting

Scores are reported **per field**. A single blended accuracy is never the
headline, because a field at 62% and a field at 99% need different work.

```
4 documents · 5 fields · overall 80.0%
  loss_amount        100.0%
  resolution_date     75.0%
  severity           100.0%
  affected_systems    75.0%
  root_cause          50.0%   <- weakest
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

### R7.1 — scoring is deterministic for every non-judge field type

The same output and gold set always produce the same score.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`)
- **Proved by:** `tests/unit/test_R007_1__non_judge_scoring_is_deterministic.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `loss_amount` `48200.00` against gold `48200.00` | correct, on every run |
| 2 | `loss_amount` `48'200.00 CHF` against gold `48200.00` CHF | correct; normalisation precedes comparison |
| 3 | `resolution_date` `28.07.2026` against gold `2026-07-28` | correct; date normalisation is part of the scorer |
| 4 | *counter-example* — `root_cause`, a free-text field | not covered; it is scored by a judge and is not deterministic (R7.11) |

### R7.2 — results are reported per field, and never as an overall figure alone

Every example here is deterministic: `root_cause`'s gold is `null` in all four
documents, so it is scored on abstention (R7.3) and needs no judge. The values
are `_fixtures.md`'s scoring example, which a person writes into the gold files.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.eval`)
- **Proved by:** `tests/acceptance/test_R007_2__scores_are_reported_per_field.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier eval incident-audit --gold gold/incidents` over `INC-4821`, `INC-4822`, `INC-4901` and `INC-5455` | every declared field is listed with its own percentage: `loss_amount` 100.0%, `resolution_date` 75.0%, `severity` 100.0%, `affected_systems` 75.0%, `root_cause` 50.0% |
| 2 | the same | `overall 80.0%` may appear, and never without the breakdown |
| 3 | the same | the weakest field, `root_cause` at 50.0%, is marked as such |
| 4 | *counter-example* — a gold set covering one field | that one field is listed; the rule is about never collapsing, not about a minimum count |

### R7.3 — a gold null is correct when the run abstains and incorrect when it supplies a value

Abstention has to be scorable, or the system learns that guessing is free.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`)
- **Proved by:** `tests/unit/test_R007_3__gold_null_scores_abstention_correct.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | gold `root_cause: null`, run abstains with a reason | correct |
| 2 | gold `root_cause: null`, run returns `"cable fault"` with a grounded span | incorrect; the document does not state it |
| 3 | gold `root_cause: "cable fault"`, run abstains | incorrect |
| 4 | *counter-example* — a field absent from the gold file entirely | not scored at all; absent is not the same as `null`, and scoring it would invent a verdict nobody verified |

### R7.4 — an ungrounded field is scored incorrect even when its value matches gold

The value being right by accident is not evidence, and accepting it would make
the grounding check decorative.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`)
- **Proved by:** `tests/unit/test_R007_4__ungrounded_field_scores_incorrect.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `loss_amount` `48200.00`, span not locatable, gold `48200.00` | incorrect |
| 2 | the same | it appears in `review.jsonl` as ungrounded rather than as a value mismatch |
| 3 | `loss_amount` `48200.00`, span locatable, gold `48200.00` | correct |
| 4 | *counter-example* — an abstaining field, which carries no span | not ungrounded and not incorrect on those grounds; it is scored against gold by R7.3 |

### R7.5 — a judge below its configured agreement threshold cannot be used as a reported metric

Given an agreement number, this is a gate with an exact answer. Producing the
number is R7.11's problem.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.judges.is_eligible`)
- **Proved by:** `tests/unit/test_R007_5__uncalibrated_judge_cannot_report.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | agreement 0.91, configured threshold 0.85 | eligible |
| 2 | agreement 0.78, configured threshold 0.85 | not eligible; `dossier eval` refuses to report that field and says why |
| 3 | agreement exactly 0.85, threshold 0.85 | eligible; the bound is inclusive |
| 4 | *counter-example* — a field scored by exact match | no judge and no threshold; the rule does not apply (R7.1) |

### R7.6 — a stale judge calibration is an error, not a warning

Agreement is re-measured whenever the judge model or its rubric changes. A
calibration measured against a different judge is not a calibration.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.judges.is_stale`)
- **Proved by:** `tests/unit/test_R007_6__stale_calibration_is_an_error.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | calibration recorded against judge model `X`, current judge model `Y` | error; `dossier eval` refuses to report that field |
| 2 | calibration recorded against rubric hash `0e52dd18`, current rubric hash differs | error |
| 3 | both unchanged since calibration | proceeds |
| 4 | *counter-example* — a judge whose *sample* grew since calibration | not stale; more gold data does not invalidate the measured agreement, it invites a re-measure |

### R7.7 — accepted corrections are versioned, attributed and timestamped

The gold set is the asset the whole system is measured against. An unattributed
edit to it is an unaudited change to the definition of correct.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.gold`)
- **Proved by:** `tests/unit/test_R007_7__gold_corrections_are_attributed.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a reviewer corrects `severity` on `INC-4821` | the gold file records `verified_by` and `verified_at` for that correction |
| 2 | the same field corrected again later | the previous value remains recoverable from version history; the file is committed to git |
| 3 | a correction with no reviewer identity | rejected; there is no anonymous path into the gold set |
| 4 | *counter-example* — a run's own output agreeing with gold | changes nothing; only a reviewer's decision enters the gold set, never a model's |

### R7.8 — `--compare` scores both configurations over the same documents and flags every regression

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/acceptance/test_R007_8__compare_reports_per_field_deltas.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | configurations `a` and `b` over the same 52 documents | a per-field table with a delta column |
| 2 | `affected_systems` moving 88.0% to 79.5% | flagged as a regression, even though the overall figure improved |
| 3 | the two configurations covering different document sets | an error; a comparison over different documents is not a comparison |
| 4 | *counter-example* — a field where both score 98.2% | reported with a delta of zero, not omitted; a silent row is indistinguishable from a missing one |

### R7.9 — every run, its per-field scores, its pinned model and its judge calibration are recorded to MLflow

Under the pipeline name, so a regression six months from now has a record to be
found in.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking`)
- **Proved by:** `tests/integration/test_R007_9__runs_are_recorded_to_mlflow.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a completed `dossier eval` of `incident-audit` | one MLflow run under experiment `incident-audit`, with one metric per field |
| 2 | the same | parameters include the pinned model identifier and the judge calibration agreement |
| 3 | MLflow unreachable | the run completes and the failure to record is reported; tracking never fails an audit |
| 4 | *counter-example* — `dossier run --plan` | records nothing; nothing was executed and nothing was scored (R4.6) |

### R7.10 — scoring performs no network I/O for non-judge field types

The direct consequence of R0.1 for this spec, and the reason most of an audit can
be re-scored offline in seconds.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`)
- **Proved by:** `tests/unit/test_R007_10__non_judge_scoring_touches_no_network.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | scoring `loss_amount`, `resolution_date` and `severity` with the network stubbed to raise | completes |
| 2 | the same, with the model client stubbed to raise on any call | completes; zero calls |
| 3 | a gold set with no free-text field at all | the whole evaluation runs offline |
| 4 | *counter-example* — scoring `root_cause` with a judge | reaches the model, by design; that is what makes it `evaluated` (R7.11) |

### R7.11 — the free-text judge agrees with human scores on the calibration sample

Measured as agreement between the judge's verdicts and a reviewer's verdicts over
the same sample. This is the number R7.5 gates on.

- **Kind:** evaluated
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/evals/test_R007_11__judge_agrees_with_human_scores.py`
- **Threshold:** OPEN — needs at least 20 human-scored `root_cause` cases before a
  number means anything, and the figure must be agreed with the domain expert who
  signs off the gold set, not chosen here
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | 20 `root_cause` cases scored by `a.muster` and by the judge | agreement at or above the agreed threshold |
| 2 | the reported figure | carries the judge model identifier and the sample size; a score without them is not reproducible |
| 3 | fewer than 20 cases available | reported as "not measurable at this N", never as a percentage |
| 4 | *counter-example* — the deterministic fields in the same run | not part of this measurement; mixing them in would flatter the judge with cases it never scored |

### R7.12 — the judge marks a planted unsupported claim as unsupported

The single case that distinguishes a working judge from one that agrees with
everything. A judge that passes every input is indistinguishable from no judge.

- **Kind:** evaluated
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/evals/test_R007_12__judge_detects_a_planted_unsupported_claim.py`
- **Threshold:** OPEN — pass on the planted case on every run is the intended bar;
  it needs the calibration sample from R7.11 to be meaningful as a rate rather
  than a single observation
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a `root_cause` naming a cause absent from `INC-4821` | the judge returns unsupported |
| 2 | the verdict asserted in the test | the boolean only; never the wording of the rationale |
| 3 | the same case against a different judge model | recorded with that model identifier; the two results are not comparable without it |
| 4 | *counter-example* — a `root_cause` that is wrong but *is* stated in the document | supported, and scored incorrect by R7.3; grounding and correctness are different questions |
