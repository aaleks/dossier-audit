# 007 — Gold sets, scoring and the change gate

**Status:** Partially implemented
**Rules:** R7.1 – R7.29

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
  "verified_by": "a.aleks",
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

What is left after those two -- a value in gold, a grounded value in the run --
is the judge's, asked the one question it was calibrated on: is this candidate
supported by the document (R7.17). Its verdict is cached like any stage's
artifact, so the judge is asked only on a miss (R7.18), and the report says how
many verdicts were judged rather than folding them silently into a percentage.

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

`dossier calibrate <pipeline> --gold gold/<name>` measures it and writes what it
measured to `gold/<name>/calibrations/<field>.json`. The agreed threshold lives
beside it in `gold/<name>/judge.yaml`, and a person writes that one -- never a
calibration run. What a judge *scored* and what it is *required* to score are
different claims, and a judge able to move its own bar is not gated by it
(R7.13, R7.14, R7.15).

Both live with the gold set rather than with the field declaration, because a
threshold is a property of scoring and the declaration is hashed into every stage
key that reads it (R6.11 row 3): raising a bar from 0.95 to 0.96 there would
re-run every extraction the pipeline has cached, to change a number no extraction
can affect.

**What an agreement figure does not say.** Agreement is one number, and it hides
three things, each of which can make a judge look better than it is
(R7.26 – R7.29):

- **How sure the figure is.** 20 of 20 is 100%, and 20 cases support a 95%
  lower bound near 84% -- which is why R7.11's bar sits below what it measured.
  The bound is the Wilson score interval's, which stays inside 0 and 1 at the
  extremes a calibration sample is often at, where the textbook interval claims
  a certainty the sample cannot give.
- **How much of it is chance.** R7.11's sample is 12 supported and 8
  unsupported, so a judge that calls every case supported agrees on 60% of it.
  Cohen's kappa measures agreement beyond what the two sets of verdicts would
  reach by chance, and puts that judge at 0.
- **Which half it gets wrong.** Catching an unsupported claim is the judge's
  whole job (R7.12). Agreement pools the supported cases with the unsupported
  ones, so a judge strong on the first can hide a weak second.

These figures are reported, not gated. Whether the bar should compare the lower
bound, or set a separate bar for unsupported cases, is a threshold, and a
threshold is a person's to agree (R7.11). These figures are what that person
needs to see first.

## Existing options considered

The Wilson interval is in statsmodels (`proportion_confint(method="wilson")`), and
kappa is in scikit-learn (`cohen_kappa_score`). Neither is used. `domain/` imports
only the standard library and pydantic, and each figure is a few lines of `math`
over four counts. Using a library would put a scoring decision outside the layer
that decisions live in, for the sake of two formulas. Decided by `a.aleks` on
2026-09-25. The tests pin the figures below, each computed by hand.

## The review loop

**Not built.** What follows is the design, kept because three rules are shaped
by it; no rule claims the file or the command, and `dossier` writes neither. The
part of it that needs no file *is* built: `dossier run` names every field finding
it produced (R6.16) and `dossier eval` names the document behind every verdict it
scored incorrect (R7.25), both with the detail described below. What is missing
is the file, and the reviewer's answers coming back.

A run would emit `review.jsonl`: one record per field that is empty,
ungrounded, low confidence, or disagrees with the gold set. A reviewer would
mark each `correct`, `incorrect`, or supply the right value, and accepted
corrections would be merged into the gold set -- reviewing being how the gold
set grows, with no separate labelling exercise.

What exists today is the material the file would hold, and two commands that
print it: every `FieldScore` carries a `detail` saying *why* it came out as it
did -- abstained, ungrounded, a value mismatch, a judge's evidence (R6.5 row 2,
R7.4 row 2, R7.17 row 2) -- and `apply_correction` in `dossier.domain.gold` is
the decision a correction would pass through (R7.7). Those details reached
nobody until R6.16 and R7.25: `field_failures` was correct, had no caller
anywhere in `src/`, and a run over sixteen invalid fields printed `0 failed`.
The command that writes the file and reads the reviewer's answers back is a
feature to scope with `/discover`, not a fix.

## The change gate

`dossier eval <pipeline> --compare <a> <b>` scores two configurations over the
same gold set and prints the per-field delta. Prompt changes, model changes and
converter changes all pass through it.

A configuration is named by the run that used it: `a` and `b` are run ids, such
as `20260806T142203Z-4f1a`. A run's manifest pins everything that can change an
output (R0.5), so each run is reproduced from its own manifest and cache, as a
replay is, and the comparison asks no model.

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
- **Status:** MET

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
| 2 | the same | its detail says it was ungrounded, not that its value mismatched -- what a review listing would show a person ("The review loop", not built) |
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

`a` and `b` are run ids, each reproduced from its own manifest and cache (see
the change gate). The same documents means both manifests pinned the same set of
document keys.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/acceptance/test_R007_8__compare_reports_per_field_deltas.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | runs `a` and `b` of `incident-audit` over the four documents of the scoring example | a per-field table: each field's score in `a`, in `b`, and the delta |
| 2 | `affected_systems` moving 75.0% to 50.0% while the overall figure moves 80.0% to 90.0% | flagged as a regression, even though the overall figure improved |
| 3 | run `b` covering a fifth document, `INC-5102`, that run `a` did not | an error; a comparison over different documents is not a comparison |
| 4 | *counter-example* — `severity` at 100.0% in both runs | reported with a delta of zero, not omitted; a silent row is indistinguishable from a missing one |

### R7.9 — every run, its per-field scores, its pinned model and its judge calibration are recorded to MLflow

Under the pipeline name, so a regression six months from now has a record to be
found in.

This rule was superseded in pieces, which is why the status line alone does not
lead a reader to everything it used to claim. Rows 1, 2 and 4 are R11.3's and
R11.1's. Row 3 is neither, and it did not merely move: **R10.5 reversed it.** An
unreachable server now refuses the command before any work, rather than letting
it complete and reporting that the record was lost. What survives of row 3 is
the narrower case where a server stops answering mid-command, which is R10.6.
Following this rule to R11.3 alone would turn up nothing about either.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.tracking`)
- **Proved by:** `tests/integration/test_R007_9__runs_are_recorded_to_mlflow.py`
- **Status:** SUPERSEDED by R11.3

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
- **Threshold:** 0.95 — agreed by `a.aleks`, who signs off the gold set, on
  2026-09-16, over the 20 human-scored `root_cause` cases. Measured 20/20 (100%)
  twice, with no case flipping between runs. The gate sits below what was
  measured on purpose: 20 of 20 at N=20 supports a 95% lower bound near 84%, so
  100% would claim more than the sample shows and would fail on the first
  genuinely borderline case added to it. A judge calling everything supported
  scores 60% here, which is the floor any figure has to clear
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | 20 `root_cause` cases scored by `a.aleks` and by the judge | agreement at or above 0.95 |
| 2 | the reported figure | carries the judge model identifier and the sample size; a score without them is not reproducible |
| 3 | fewer than 20 cases available | reported as "not measurable at this N", never as a percentage |
| 4 | *counter-example* — the deterministic fields in the same run | not part of this measurement; mixing them in would flatter the judge with cases it never scored |

### R7.12 — the judge marks a planted unsupported claim as unsupported

The single case that distinguishes a working judge from one that agrees with
everything. A judge that passes every input is indistinguishable from no judge.

The case is planted in `INC-4830`, which states its root cause: the quarter-end
change freeze it names only as a contributing factor, offered instead as the
cause of the outage. That is what a planted claim needs -- plausible, adjacent to
the truth, and stated nowhere. `INC-4821` states no cause at all, so nothing
planted in it would be distinguishable from anything else absent from it.

- **Kind:** evaluated
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/evals/test_R007_12__judge_detects_a_planted_unsupported_claim.py`
- **Threshold:** the planted case is marked unsupported on every run — agreed by
  `a.aleks` on 2026-09-16, alongside R7.11's 0.95. Deliberately not a rate: it is
  one case, and it either holds or the judge is indistinguishable from no judge.
  R7.11's sample is what makes the single observation mean anything -- `rc-02` is
  one of the eight unsupported cases the judge called correctly out of eight, so
  passing it is not a coin landing the right way up
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a `root_cause` naming a cause absent from `INC-4830` | the judge returns unsupported |
| 2 | the verdict asserted in the test | the boolean only; never the wording of the rationale |
| 3 | the same case against a different judge model | recorded with that model identifier; the two results are not comparable without it |
| 4 | *counter-example* — a `root_cause` that is wrong but *is* stated in the document | supported, and scored incorrect by R7.3; grounding and correctness are different questions |

### R7.13 — a judge's agreement threshold is declared with the gold set, never with the field declaration

A threshold is a property of scoring, not of extraction. The field declaration is
hashed as text into every stage key that reads it (R6.11 row 3), so a bar raised
from 0.95 to 0.96 there would re-run every extraction the pipeline has cached --
to change a number no extraction can affect. The gold set is what the judge is
measured against, is a workspace asset one set can serve several pipelines with
(R3.7), and is in no key.

`gold/<name>/judge.yaml` holds one threshold per judged field. YAML rather than
JSON so that it cannot be read as one of the `<document>.json` files a gold set
is made of (R3.7 row 1).

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R007_13__a_judge_threshold_is_declared_with_the_gold_set.py`, `tests/acceptance/test_R007_15__eval_withholds_an_ungated_judged_field.py`
- **Status:** SUPERSEDED by R7.20

| # | Given | Then |
|---|-------|------|
| 1 | `gold/incidents/judge.yaml` declaring `root_cause: 0.95` | the figure `dossier eval` gates `root_cause` on (R7.5) |
| 2 | a `free_text` field with no threshold declared for it | load-time error naming the field and the file; a judged field with no bar would be reported as though it had cleared one |
| 3 | a threshold written `95` rather than `0.95` | load-time error; agreement is a proportion, and 95 would make every judge ineligible forever while reading like strict configuration |
| 4 | *counter-example* — a threshold changed between two evals | no stage key moves; the run is re-scored and nothing is re-extracted (R5.3 row 4) |
| 5 | *counter-example* — `--gold gold/incidents` whose `judge.yaml` says nothing about `root_cause`, from a pipeline declaring no `gold:` | not a load-time error: the pipeline committed to no gold set, so there was nothing to check when it loaded. The field is withheld when the set is read, saying no threshold is declared in `judge.yaml` (R7.15); a percentage is still never printed for it |

### R7.14 — `dossier calibrate` measures a judge against the gold set's sample and writes the calibration beside it

Producing the figure is R7.11. This rule is where it is kept, and why it is kept
apart from the bar it is judged against: a calibration is measured, a threshold is
agreed by a person (R7.11's was agreed by `a.aleks`), and a re-measure that could
rewrite the bar would be a judge grading its own paper.

It is measured against the **sample**, not against the gold answers, and the
difference is not a detail. A gold file says what the right value *is*. Measuring
a judge needs candidate answers a human has marked supported or unsupported,
including wrong ones -- R7.12's planted case *is* a wrong candidate, and a gold
file has nowhere to put one. The sample is `gold/<name>/samples/<field>.jsonl`,
and R7.16 says what a record in it holds.

`gold/<name>/calibrations/<field>.json` holds what R7.11 measured -- the judge
model, the rubric hash, the agreement and the sample size -- one file per judged
field, under a subdirectory so it is not one of the `<document>.json` files the
gold set is made of (R3.7 row 1).

The rubric is the one the field declaration names in its `judge:` key (spec 006),
and the hash is of that file's text. The model and the rubric travel with the
figure because a measurement made against another judge, or another rubric, is
not this judge's calibration -- which is exactly what R7.6 compares them for.

What a calibration run records to MLflow is R11.5: the same figures this file
holds, plus the measurements the file cannot keep -- every run rather than the
latest, and a trace per case behind the agreement figure.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/unit/test_R007_14__agreement_is_measured_over_the_reviewers_cases.py`, `tests/unit/test_R007_14__calibrate_writes_what_it_measured.py`, `tests/acceptance/test_R007_14__calibrate_writes_the_calibration_file.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier calibrate incident-audit --gold gold/incidents`, whose `samples/root_cause.jsonl` holds 20 human-scored cases | `gold/incidents/calibrations/root_cause.json` holding the judge model, the rubric hash, the agreement and the sample size |
| 2 | the judge model or the rubric changed since the last run | the new measurement replaces the old; the file records what is true now, and R7.6 is what notices the old one was stale |
| 3 | a sample of fewer than 20 cases | refused, naming the count; not measurable at this N, never rounded into a percentage (R7.11 row 3) |
| 4 | a judged field with no `samples/<field>.jsonl` at all | refused, naming the field and the path it looked for; a judge cannot be measured against a sample nobody has written |
| 5 | *counter-example* — `gold/incidents/judge.yaml` | never written and never read by the measurement; the bar is agreed by a person, and a calibration run may not move it |

### R7.15 — `dossier eval` withholds a judged field whose calibration is missing, short or stale

R7.5 and R7.6 are pure decisions with tests, and until something loads a
calibration and a threshold neither can fire from a command: a field whose judge
has never been measured still prints a percentage, which is the one thing R7.5
exists to prevent. This rule is what makes both reachable.

Withheld rather than printed as zero, and named rather than omitted: a missing
line reads as a field nobody verified (R7.3 row 4), which is a different problem
and wants different work.

The report is therefore written from the **declared** fields, not from the
scored ones. A withheld field whose every verdict went to the judge has nothing
deterministic to total, and a report built from the totals dropped it entirely --
silently, and exactly in the case the withholding matters most, where the judge
was the only thing that could have answered. `--compare` has always walked the
declaration for this reason (R7.8); this says the single-run report does too.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.eval`)
- **Proved by:** `tests/unit/test_R007_15__why_a_judged_field_is_withheld.py`, `tests/acceptance/test_R007_15__eval_withholds_an_ungated_judged_field.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause` calibrated at 0.91 against a declared 0.95 | no `root_cause` percentage; a line naming the field, the agreement and the bar it missed (R7.5) |
| 2 | a calibration measured against `openai:gpt-5.4-mini` where the pipeline now names another judge | no percentage; a line saying the calibration is stale and which half moved (R7.6) |
| 3 | `root_cause` with no calibration file at all | no percentage; a line saying it was never measured, which is not the same as measured and found wanting |
| 4 | `root_cause` calibrated at 0.95 against a declared 0.95 | reported; the bound is inclusive (R7.5 row 3) |
| 5 | a withheld `root_cause` whose every verdict was deferred — gold states a value for every document and every run answer is grounded | the line is still printed with its reason; there is no deterministic verdict to total, and a field that vanished would read as one nobody verified |
| 6 | *counter-example* — `severity`, scored by exact match | reported; no judge, no threshold, and no calibration that could be stale (R7.1) |
| 7 | *counter-example* — a declared field no gold file mentions at all | no line; absent is not withheld, and inventing one would report a field nobody verified as a field somebody refused (R7.3 row 4) |

### R7.16 — a calibration sample records candidate answers a human marked supported or unsupported

The gold set and the sample answer different questions, and one file cannot do
both. A gold file says what the right value *is*, and is what R7.3 scores a run
against. A sample record says whether a *candidate* answer is supported by its
document -- which is the question a judge is asked, and the only question its
agreement can be measured on. So a sample must be able to hold an answer that is
wrong: R7.12's planted case is exactly that, and a gold file has nowhere to put
one.

One record per line at `gold/<name>/samples/<field>.jsonl`: the document, the
candidate answer, the verdict, and who verified it and when (R7.7's shape). JSONL
rather than a file per case because a sample is read whole and in order, and a
reviewer grows it by appending.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R007_16__a_calibration_sample_holds_verified_verdicts.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a record holding `document`, `answer`, `supported` and `verified_by` | accepted; that is the whole shape a measurement needs |
| 2 | a record with no `verified_by` | refused, naming the line; an unattributed verdict is an unaudited definition of correct (R7.7) |
| 3 | a record whose `supported` is `"false"` rather than `false` | refused, naming the line; every non-empty string is truthy, so a sample read that way would score the judge against nonsense and report a percentage for it |
| 4 | *counter-example* — a gold file's `root_cause` value | not a sample record; it says what the answer is, never whether a candidate is supported |

### R7.17 — a free-text field with a value in gold and a grounded value in the run is scored by the judge, asked the calibrated question of the run's answer

Everything before this rule decided what a judge is *allowed* to say and never
asked it: `dossier eval` deferred every free-text verdict to a judge and then
dropped it, so `root_cause 50.0%` was a percentage over the abstention cases
alone, and the whole gate -- threshold, sample, calibration, withholding --
guarded a number nothing produced.

The question is the one the judge was measured on, and no other: is this
candidate supported by the document (R7.16). Not "does it match the verified
answer". The sample holds candidates and verdicts, the threshold was agreed
over that question (R7.11), and a judge asked a different one in `eval` would be
gated by a calibration of something else. So gold's text is a reference for the
person reviewing, and what gold contributes to the verdict is whether it is
`null` (R7.3). A run answer that is supported but names a cause the reviewer
did not scores correct under this rule; catching that is a second question, a
second sample, and a second threshold, and is deliberately not this rule.

The judge decides only what is left. Abstention (R7.3) and grounding (R7.4) are
decided first, as facts, and a field that may not be reported (R7.15) is not
judged at all: nothing is measured for a number nobody may quote, and twenty
judge calls for a withheld field is the cost the gate exists to spare.

The report says how many verdicts were judged. A percentage over an unknown mix
of abstention verdicts and judged ones is the silent subset this rule replaces.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/unit/test_R007_17__a_free_text_field_is_scored_by_the_judge.py`, `tests/acceptance/test_R007_17__eval_scores_free_text_with_the_judge.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4830`, gold `root_cause` stated, the run answering `rc-01`'s wording, grounded; judge eligible | 1 judge call; supported, so correct |
| 2 | the same, the run answering `rc-02`'s wording -- the planted claim | 1 judge call; unsupported, so incorrect, with the judge's evidence as the reason (R7.12) |
| 3 | the report line for `root_cause` over the scoring example's four abstention verdicts and `INC-4830`'s judged one | `root_cause  60.0%   (1 judged)`; the count is printed, never implied |
| 4 | *counter-example* — gold `root_cause: null`, or the run abstains | R7.3 decides; 0 judge calls |
| 5 | *counter-example* — the run's value has no locatable span | R7.4 decides, incorrect; 0 judge calls |
| 6 | *counter-example* — `root_cause` withheld: never measured, stale, or below the bar | withheld as R7.15 says, and 0 judge calls; nothing is measured for a field nobody may quote |
| 7 | *counter-example* — `dossier eval incident-audit --compare a b` with `root_cause` withheld | withheld on both sides, printing its reason and no delta; the change gate is the place a judge's number is most likely to be quoted, and it is gated the same way |

### R7.18 — a judge verdict is cached under the judge model, the rubric hash, the judge prompt hash, the document's text hash and the candidate answer, and the judge is asked only on a miss

R0.10's promise: a model is asked only on a cache miss, and everything right of
the boundary reproduces without one. A judge is a model. Its verdict is an
artifact like any stage's -- a content-addressed file with a provenance record
(R0.3), in its own namespace beside `stage` and `convert` -- so a second eval
of the same run asks nothing, a comparison over two runs whose candidate is the
same asks nothing, and a run that changed one document's answer asks about that
candidate alone.

The key names what can change the verdict and nothing else: which judge, what
it was asked (the rubric and the wrapper dossier puts it in), what it was shown
(the document's converted text) and what it was asked about (the candidate).
The gold set is not in it -- a verdict on a candidate is the same whichever
gold set it is scored against -- and neither is the run id.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/unit/test_R007_18__a_judge_verdict_is_cached_and_the_judge_asked_on_a_miss.py`, `tests/acceptance/test_R007_18__eval_asks_the_judge_only_on_a_miss.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the first `dossier eval` over `INC-4830`, nothing cached | 1 judge call; the verdict written under `.dossier/cache/judge/` with a provenance record naming the five inputs |
| 2 | the same eval again | 0 judge calls; the same verdict, byte for byte (R5.5) |
| 3 | `--compare a b` where run `b` answered `INC-4830` exactly as run `a` did | 0 judge calls |
| 4 | run `c` answering `INC-4830` differently | 1 judge call, for that candidate only (R5.7's shape) |
| 5 | with tracking on, a judged `root_cause` over `INC-4830` served from cache | one trace on the eval's run, tagged `dossier.document` and `dossier.field`, with no LLM span in it; a miss holds one (R11.2 row 3's shape, R11.3) |
| 6 | *counter-example* — `dossier run --plan`, `--replay` | the judge is never asked and no verdict is read (R4.6, R4.7) |

### R7.19 — a calibration is stale when the judge prompt has changed since it was measured

The rubric is the pipeline author's, and its hash is in the calibration (R7.14).
The wrapper dossier puts the rubric in -- the document, the claim, the output
format -- is dossier's, and until this rule it was in no hash: an edit to it
changed what every judge was asked while every calibration read as fresh, which
is exactly what R7.6 exists to notice. The same reasoning added R6.12: a change
to dossier's own text moves a key, whatever the author's files did.

A calibration records the prompt's hash beside the rubric's, and `is_stale`
compares both. A calibration file from before this rule has no prompt hash and
is read as stale, naming the field: it was measured under a prompt nobody
recorded, which is not the same as measured under this one.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.judges.is_stale`)
- **Proved by:** `tests/unit/test_R007_19__a_changed_judge_prompt_makes_a_calibration_stale.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the judge prompt edited; rubric and judge model unchanged | stale; `dossier eval` withholds the field saying the judge prompt has changed |
| 2 | a `calibrations/root_cause.json` with no `prompt_hash` | stale, naming the missing field; measured under a prompt nobody recorded |
| 3 | *counter-example* — rubric, judge model and prompt all unchanged | proceeds (R7.6 row 3) |

### R7.20 — a judged field's agreement threshold is declared per grounding state

R7.13 gave `gold/<name>/judge.yaml` one threshold per judged field, which was
right while there was one way to answer a field. R6.15 added a second:
`root_cause` can be answered from text a search can confirm, or read off a page
by a model looking at it. Those are two different judges asked two different
questions, and they do not measure the same.

They also do not score the same. Over the twenty-two case visual sample,
`openai:gpt-5.4-mini` agreed with `a.aleks` on 21 — twice, with no case flipping
— against 20 of 20 on the text sample. One bar for both would gate a `described`
verdict on a figure measured against text, which is R7.15's failure with the
paperwork in order.

A scalar stays valid and means the `grounded` bar, so a gold set written before
this rule loads unchanged — R3.11's bargain, for the same reason. A `described`
bar is required only where a `described` verdict can arise: a `per_part` step is
the only thing that hands a stage a picture (R3.12), so it is the only thing
that can produce one.

Everything R7.13 says about *where* the threshold lives is unchanged and is
restated here rather than referred to: the gold set, never the field
declaration, because the declaration is hashed into every stage key that reads
it (R6.11 row 3) and a bar is in no key.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load.load_judge_thresholds`)
- **Proved by:** `tests/unit/test_R007_20__a_threshold_is_declared_per_grounding_state.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause: {grounded: 0.95, described: 0.90}` | both figures are read; `dossier eval` gates each verdict on the bar for the state it was decided in |
| 2 | `root_cause: 0.95`, a scalar | `{grounded: 0.95}`; every gold set written before this rule loads unchanged, and declares nothing about a state it could not produce |
| 3 | a judged field produced by a `per_part` step, with only `grounded` declared | load-time error naming the field and `described`; that step can hand a stage a picture, so it can produce a verdict this file has no bar for |
| 4 | `root_cause: {visual: 0.9}` | load-time error naming `visual` and the two states that exist; a bar under a name nothing reads gates nothing, and looks like it gates something |
| 5 | `root_cause: {grounded: 95}` | load-time error; a proportion is a proportion in either shape (R7.13 row 3) |
| 6 | *counter-example* — a judged field produced by a `per_file` step, `grounded` only | loads; no step in this pipeline can produce a described field, so a bar for one would gate nothing and asking for it would be ceremony |

### R7.21 — a `described` field is put to the judge with the document's pages in place of its text

R6.15 made `described` a verdict a run can produce. R7.17 then hands every
deferred free-text field to the judge with `judging.documents[document]` — the
converted text — and a document shown as pictures has none. Today that is a
`KeyError` on a picture-only document, which is the whole of `dossier eval`
falling over on the evidence the visual slice exists to read.

The judge is shown what the stage was shown: one image per page, in page order,
with a body saying so in place of a transcript. That sentence is fixed text and
not a rubric, and it is the sentence the `described` bar was measured with — a
prompt edited afterwards asks a different question of the same threshold, which
R7.19 already treats as staleness.

The pages enter the verdict's key where the document's text hash does, so a
described verdict and a grounded one about the same candidate are two entries,
and neither serves the other (R7.18).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.judge_scores`)
- **Proved by:** `tests/unit/test_R007_21__a_described_field_is_judged_from_the_pages.py`, `tests/acceptance/test_R007_21__eval_judges_a_chart_from_its_pages.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause` described on `INC-5720`, whose source declares `convert: [page_images]` | the judge is asked once with the page as an image part, and a body saying the pages are shown rather than the document's text |
| 2 | the same field on a grounded record | asked with the converted text and no parts; nothing about the text judge moves (R7.17) |
| 3 | the same described candidate judged twice | one call; the second is served from the `judge` namespace, keyed on the pages (R7.18) |
| 4 | a grounded and a described verdict on the same candidate and the same document | two entries and two calls; the pages and the text are different evidence for one claim |
| 5 | *counter-example* — a described field on a document the workspace holds no pages for | no verdict; the field is left unscored for that document rather than judged against an empty prompt |

### R7.22 — `dossier calibrate` measures each grounding state against its own sample

A judge shown pages and a judge shown text are two judges asked two questions,
so they are measured separately and recorded separately: `samples/<field>.jsonl`
and `calibrations/<field>.json` for `grounded`, `samples/<field>.described.jsonl`
and `calibrations/<field>.described.json` for `described`. The `grounded` names
are unchanged, so every gold set written before R7.20 is read by the same paths.

Only for a state the pipeline can produce. A pipeline with no `per_part` step is
asked for no described sample, because nothing in it can produce a described
verdict and a sample for one would be twenty cases nobody can act on (R7.20).

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.calibrate_fields`)
- **Proved by:** `tests/unit/test_R007_22__each_grounding_state_is_measured_on_its_own_sample.py`, `tests/acceptance/test_R007_22__calibrate_writes_one_calibration_per_state.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | a pipeline with a `per_part` step, both samples present | two files: `calibrations/root_cause.json` and `calibrations/root_cause.described.json`, each carrying the judge model and the size of the sample it came from |
| 2 | the described sample, measured | the judge is shown page images and the same fixed body R7.21 uses; a state measured on a prompt it is not asked with is a figure about nothing |
| 3 | a described sample of 19 cases | refused before a single judge call, naming the field and the state (R7.14 row 3) |
| 4 | a `per_part` pipeline with no `samples/<field>.described.jsonl` | the command names the missing sample and its path, and exits non-zero |
| 5 | *counter-example* — a pipeline whose only step is `per_file` | one calibration, and no described sample is looked for at all |

### R7.23 — a judged field is reported only when every state it can produce is calibrated and above its own bar

R7.15 withholds a field whose calibration is missing, short or stale. With two
states a field has two calibrations, and a field's percentage mixes verdicts
from both — so a figure printed while one half was never measured is the number
R7.5 exists to refuse, arrived at more elaborately.

Withheld whole, not by state. A field reported as "0.82, of which the described
verdicts are ungated" is a number every reader will quote without the clause.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main._judge_gate`)
- **Proved by:** `tests/unit/test_R007_23__a_field_is_reported_only_when_every_state_clears.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `grounded` measured 0.97 against 0.95 and `described` 0.95 against 0.90 | the field is reported, and its percentage covers verdicts of both kinds |
| 2 | `described` never measured, `grounded` clear | the whole field is withheld, and the reason names `described` and says it was never measured |
| 3 | `described` measured 0.86 against a bar of 0.90 | withheld, naming the state, the figure and the bar — three different fixes, as R7.15 says |
| 4 | `grounded` below its bar and `described` above | withheld; either half failing makes the one number untrustworthy |
| 5 | *counter-example* — a pipeline with no `per_part` step | only `grounded` is consulted, and a missing described calibration withholds nothing |

### R7.24 — the vision judge agrees with human scores on the visual calibration sample

R7.11 for the other judge. The question is the same one — is this candidate
supported by this document — asked of a document supplied as pictures, and the
figure is what the `described` bar in `judge.yaml` was set from.

`openai:gpt-5.4-mini` agreed with `a.aleks` on 21 of the 22 cases in
`root_cause_visual.jsonl`, twice, with no case flipping between runs. Twenty of
those cases are carried from `root_cause.jsonl` — the same proposition about the
same document, differing only in what the judge is shown — and two are on
`INC-5720`, which has no text layer and so cannot be put to the text judge at
all.

The one disagreement is recorded rather than smoothed away: on `INC-5455` the
judge called a hypothesis the document explicitly leaves unproven *supported*,
reading a four-column table's `Verdict` column as an assertion in a document
whose every page header says the root cause was never established. The text
judge scores that case correctly. Prose it reads; a table's column semantics it
loses — which is why the bar is below the text judge's, and why it is not 1.0.

- **Kind:** evaluated
- **Layer:** infrastructure (`dossier.infrastructure.models`)
- **Threshold:** 0.90 agreement over `tests/evals/golden/root_cause_visual.jsonl`, agreed by `a.aleks` on 2026-09-19
- **Proved by:** `tests/evals/test_R007_24__vision_judge_agrees_with_human_scores.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the 22 human-scored visual cases put to `openai:gpt-5.4-mini` as page images | agreement at or above 0.90 |
| 2 | the same measurement recorded | the judge model and the size of the sample travel with the figure, as R7.11 row 2 requires |
| 3 | a judge answering "supported" to every case | 13 of 22 = 0.591, the floor the bar must clear to measure anything |
| 4 | *counter-example* — the same sample scored by a judge shown extracted text | not comparable, and not a substitute: `INC-5720` has no text layer, so two of the cases cannot be asked at all |

### R7.25 — `dossier eval` names the document behind every verdict it scored incorrect, with the detail that says why

R7.2 gives each field a percentage, which says where the work is. It does not say
what the work *is*, and the material to say it has been carried since scoring was
written: every `FieldScore` holds a `detail` distinguishing an ungrounded field
from a value that disagreed from a malformed one (R7.4 row 2), and "The review
loop" above describes the file those details would one day fill. The file is
still not built. This rule is the part of it that needs no file: the details are
printed, under the field whose percentage they explain, as each eval runs.

The distinction R7.4 row 2 exists for is the whole point. A field at 0.0% is three
different problems -- a prompt that cites nothing locatable, a model that reads
the wrong figure, a gold set that moved -- and they are told apart by reading the
detail, not by reading the percentage a second time.

Every miss is named, not a sample of them. A cap would be a number nobody
measured, and "and 14 more" is the shape of a report that knows something it is
not saying; a large corpus is what a pipe is for. Only the misses: a correct
verdict has no detail worth a line, and printing one per field per document would
bury the fifteen that matter under four hundred that do not.

A withheld field prints its reason and no details (R7.15). Nothing was scored for
it, so there is nothing to explain -- and a list of misses under a field whose
percentage was refused would be the number arriving by the back door.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R007_25__eval_names_the_documents_behind_a_score.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `loss_amount` at 25.0% over four documents | the `loss_amount` line, then one indented line per incorrect verdict, each naming its document and its detail |
| 2 | `PLAY-1001.md`'s `loss_amount` scored incorrect for citing a key that is not an input | `    PLAY-1001.md  loss_amount: cites 'PLAY-1001', which was not an input to this stage. Inputs were ['PLAY-1001.md'] (R6.3)` |
| 3 | `PLAY-1001.md`'s `loss_amount` ungrounded, its value matching gold | the detail says it was ungrounded, not that its value mismatched (R7.4 row 2) |
| 4 | a field at 100.0% | its line alone; a correct verdict has no detail worth a line |
| 5 | documents in the order the run visited them | the same order under every field, so two evals of one run read identically (R0.4) |
| 6 | *counter-example* — a withheld `root_cause` | its reason line, and no details; nothing was scored, so there is nothing to explain (R7.15) |
| 7 | *counter-example* — a field absent from gold for one document | no line for that document; absent is not `null` and is not a miss (R7.3 row 4) |

### R7.26 — a calibration reports the 95% Wilson lower bound on its agreement

The bound is taken over the same cases as the agreement, and a case the judge
could not be asked counts as a disagreement, as it does in the agreement
(R7.11). The z it uses is the 0.975 quantile of the standard normal,
`statistics.NormalDist().inv_cdf(0.975)`, taken rather than typed as 1.96, so the
bound is a function of the two counts alone and comes out the same on every
machine (R0.4).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.judges`)
- **Proved by:** `tests/unit/test_R007_26__a_calibration_reports_the_lower_bound_on_its_agreement.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | 20 of 20 `root_cause` cases agreed | agreement 100.0%, lower bound 83.9% -- the figure R7.11's threshold note reasons with |
| 2 | 19 of 20 agreed | agreement 95.0%, lower bound 76.4%: one miss costs 5 points of agreement and 7.5 of the bound |
| 3 | 38 of 40 agreed, the same 95% | lower bound 83.5%; a larger sample earns a tighter bound, so the count is read and not only the ratio |
| 4 | *counter-example* — 20 of 20 against R7.11's bar of 0.95 | `root_cause` reported by `dossier eval` as before; the bound gates nothing, and R7.5 still compares the agreement |

### R7.27 — a calibration reports Cohen's kappa between the judge and the reviewer

Kappa is agreement beyond what chance would give: the observed agreement less the
agreement expected from how often each side said supported, over what is left of
1 after that expectation. A case the judge could not be asked counts as the
opposite of the reviewer's verdict, so kappa and the agreement count the same
disagreements.

It is not measurable when the reviewer marked every case the same way. Chance
agreement then depends on the judge alone, and kappa comes out 0 or undefined
whatever the judge did -- a figure that would say nothing while looking like a
measurement.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.judges`)
- **Proved by:** `tests/unit/test_R007_27__a_calibration_reports_kappa.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | 20 of 20 agreed, 12 cases supported and 8 unsupported | kappa 1.00 |
| 2 | a judge that calls all 20 supported | agreement 60.0% and kappa 0.00: every agreement it has is what chance would give |
| 3 | 19 of 20 agreed, the miss an unsupported case called supported | kappa 0.89 |
| 4 | *counter-example* — the reviewer marked all 20 supported, and the judge agreed on every one | kappa not measurable, never 0 or 1; a sample with one verdict in it cannot tell agreement from chance |

### R7.28 — a calibration reports the supported and the unsupported cases apart, each as how many the judge agreed on out of how many there were

Counts, not only rates: 8 of 8 and 80 of 80 are both 100%, and only the count
says how far to trust it. A case the judge could not be asked counts against its
own half, as it counts against the agreement.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.judges`)
- **Proved by:** `tests/unit/test_R007_28__supported_and_unsupported_cases_are_reported_apart.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | 20 of 20 agreed, 12 cases supported and 8 unsupported | supported 12 of 12, unsupported 8 of 8 |
| 2 | a judge that calls all 20 supported | supported 12 of 12, unsupported 0 of 8: 60% agreement, and none of the claims it exists to catch |
| 3 | no verdict for one supported case, every other case agreed | supported 11 of 12, unsupported 8 of 8 |
| 4 | *counter-example* — a sample with no unsupported case | `no unsupported case`, never 0 of 0 as a percentage: there was nothing to catch, which is not the same as catching it |

### R7.29 — `dossier calibrate` prints, writes and records the same lower bound, kappa and counts

The figures of R7.26 – R7.28 go everywhere the agreement already goes. The
terminal gets one more line under each judge's agreement line (R7.14), in plain
words. `calibrations/<field>.json` holds them beside the agreement. The calibrate
run holds them as metrics (R11.5) and in its description (R11.17), rounded as the
terminal prints them, so the file, the terminal and MLflow cannot disagree.

A figure that is not measurable is `null` in the file, said in words in the
terminal, and sent as no metric at all. MLflow has no null, and a 0 standing in
for one would be charted as a judge that scored 0.

A calibration file written before these figures still loads and gates as it did:
every new figure in it is optional, and the gate reads the agreement (R7.5).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.judges.Calibration`, `dossier.domain.tracking`), application (`dossier.application.eval.calibrate_fields`)
- **Proved by:** `tests/unit/test_R007_29__calibrate_prints_writes_and_records_the_same_figures.py`, `tests/acceptance/test_R007_29__calibrate_reports_what_its_agreement_hides.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier calibrate incident-audit --gold gold/incidents`, 20 of 20 agreed | under `root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini`, the line `                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8` |
| 2 | the same | `calibrations/root_cause.json` gains `lower_bound` 0.8389…, `kappa` 1.0, `supported` `{"agreed": 12, "cases": 12}` and `unsupported` `{"agreed": 8, "cases": 8}`; the run gains metrics `judge/root_cause/lower_bound` 83.9, `judge/root_cause/kappa` 1.0, `judge/root_cause/supported` 100.0 and `judge/root_cause/unsupported` 100.0 |
| 3 | a `per_part` pipeline, both samples measured | the same figures for `root_cause.described`, in its own file and under its own metric names (R7.22) |
| 4 | a sample the reviewer marked all supported, 20 of 20 agreed | `kappa not measurable` and `no unsupported case` in the terminal; `kappa` `null` and `unsupported` `{"agreed": 0, "cases": 0}` in the file; no `kappa` or `unsupported` metric |
| 5 | *counter-example* — a `calibrations/root_cause.json` written before R7.26 | loads, and `dossier eval` withholds or reports `root_cause` exactly as before (R7.15); the gate reads the agreement alone |
