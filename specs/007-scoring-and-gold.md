# 007 — Gold sets, scoring and the change gate

**Status:** Partially implemented
**Rules:** R7.1 – R7.51

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
| boolean (auto-renews, signed) | the same truth value | no |
| duration (notice period, term) | the same length, within one calendar unit family | no |
| list (affected systems, parties) | the same set of items, each compared as text with case folded | no |
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

**A boolean is `true` or `false`, and only `null` abstains.** The strings
`"true"` and `"false"` read as the same values in any case, because whether a
model wrote a JSON value in quotes is not information, as the case of an enum is
not. Nothing else is a boolean: `1` is a number and `yes` is a word, and reading
either would begin a vocabulary (`y`, `on`, `ja`) nobody agreed to. `false` is an
answer and needs its evidence as any other value does (R6.6); "the contract does
not say" is `null` with a reason, and a run that answers `false` where gold
abstains is scored as supplying a value (R7.3, R7.36 row 7).

**A duration is a whole number of days, weeks, months or years.** `90 days`,
`1 Year` and ISO 8601's `P90D` all read. A bare `90` does not: ninety of what is
the question `07/08/2026` asks, and it is refused for the same reason. Nor does
`90 business days`, whose length depends on a calendar, or `P1Y6M`, which has
two units where `18 months` has one (R7.37).

Two durations are the same answer when they are the same length, and lengths
convert only where the conversion is exact: seven days to a week, twelve months
to a year. **A month is never a number of days**, nor a year: three months is 89
to 92 days depending on where it starts, and a contract that gives three months'
notice and one that gives ninety days' notice give different notice. So `3 months`
against a gold `90 days` is incorrect, and the detail says why (R7.38).

**A list is the set of its items.** A `list` field is answered one record per
item (spec 006, "A list is answered one record per item") and scored as one
answer per document: correct when the run's items and gold's are the same set
(R7.40, R7.41). Order is not information, and a system named on two pages is one
system named. An item is compared as a `reference` is, as text with its case
folded and its surrounding whitespace trimmed, and it matches whole: `payments`
is not `payments-api`. One ungrounded item makes the list incorrect, as an
ungrounded value makes any field incorrect (R7.4): a list is not more right for
being mostly grounded (R7.42).

Gold writes a list as an array, `{"value": ["payments-api", "ledger-batch"]}`,
and never as one string: splitting `"payments-api, ledger-batch"` on its comma
would be a guess, and an item may hold a comma. An empty array is refused, and
`null` with a reason written instead. A run answering one record per item says
"there are none" and "the document does not say" the same way, as an abstention
with a reason, so a gold set able to hold the difference would score it against
answers that cannot (R7.44).

**A list reports its items as well as its verdict.** One verdict per document
says a list was wrong, not whether the run missed systems or invented them. So a
list's line carries its item precision -- of the items the run named, how many
gold names -- and its recall -- of gold's items, how many the run named -- each
summed over the documents scored. They are reported and not gated, as a
calibration's lower bound and kappa are (R7.26, R7.27): the percentage is what
`--compare` gates on (R7.8), and a gate on either would need a threshold nobody
has agreed (R7.43).

**A field is one answer per document, however many pages gave it.** A
`per_part` step asks once per page (R3.12), and a document's fields are its
pages' fields, so `INC-4830`'s `severity`, printed in the header of each of its
three pages, comes back three times. Scored once per page, a three-page document
weighed three times what a one-page document did, and a page that said "not on
this page" was a miss against gold's value. So the pages are scored together, as
one verdict for their document (R7.46). A page that abstains says nothing about
its document while another page gives a value, and the document abstains only
when every page does (R7.47). The field is correct only when every page that gave
a value is correct: a run that answers `2026-07-28` on page 1 and `2026-07-30`
on page 2 has given two answers to one question, which is R6.24's reason for
refusing one reply that does it, and R7.42's for failing a list one of whose
items is wrong (R7.48). A judged field is judged page by page on the same terms
(R7.49).

**A field gold verifies and the run never answered is scored as an
abstention.** A step's answer may leave a declared field out: the record shape
requires none of them, and a `per_part` prompt tells a page to leave out what it
cannot see. Scored only by the records that exist, a left-out field got no verdict
at all, so a run that left out every field it was unsure of was never wrong about
one. That is what R7.3 exists to prevent, so a field with no record is scored as
if the run had abstained: correct when gold says `null`, incorrect when gold has a
value, and named `not answered` rather than `abstained` (R7.50).

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

The lower bound and kappa are reported, not gated. The unsupported half can be
gated: a gold set may give it a bar of its own, beside the agreement bar
(R7.30, R7.31). That was agreed after these figures had been seen on real
calibrations, because a threshold is a person's to agree (R7.11).

## Existing options considered

The Wilson interval is in statsmodels (`proportion_confint(method="wilson")`), and
kappa is in scikit-learn (`cohen_kappa_score`). Neither is used. `domain/` imports
only the standard library and pydantic, and each figure is a few lines of `math`
over four counts. Using a library would put a scoring decision outside the layer
that decisions live in, for the sake of two formulas. Decided by `a.aleks` on
2026-09-25. The tests pin the figures below, each computed by hand.

Durations are read the same way, for the same reason. pydantic reads ISO 8601
durations into a `timedelta`, which has no months or years, so it cannot hold
the one distinction R7.38 exists to keep. `isodate` reads `P3M` as three months,
and lives outside what `domain/` may import. What R7.37 reads is a number and one
of four units, a few lines of `re`. Decided by `a.aleks` on 2026-09-28.

A list's item precision and recall are the standard micro-averaged figures,
what scikit-learn's `precision_score(average="micro")` computes over a
multi-label set. Three sums over sets cost less than a dependency the purity
boundary would not admit, so they are written in `domain/` beside the others.
That a list is answered one record per item, and scored as an exact set with the
two figures reported beside it, was decided by `a.aleks` on 2026-09-28.

How a document's pages are scored together is this project's own question about
its own records, and no library has an opinion on it. Four answers were weighed:

| Option | For | Against |
|---|---|---|
| **Every page that gave a value must be correct** (adopted) | counts documents, as R7.41 says a percentage does; a contradiction between pages is caught; a page may abstain on what it cannot see; each page is scored by the scorer that already exists | one misread page fails a document whose other pages were right |
| Any page correct is enough | forgiving of a noisy page | `major` on page 1 and `minor` on page 3 is correct, so answering every value on every page pays; whoever reads the answer still sees two |
| The first page in part order that gave a value | the least to build | a wrong answer on a later page never reaches the score; which page is first is layout, not evidence |
| Refuse `output:` on a `per_part` step, and reconcile in a `per_file` step after it | the model reconciles with every page in view; scoring is untouched | a `described` field exists only on a `per_part` step's output (R6.15, R7.21), so it would take the vision judge with it; one more call per document |

That every page that gave a value must be correct, and that a field with no record
is scored as an abstention in every mode, was decided by `a.aleks` on 2026-09-28.

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
- **Layer:** cli (`dossier.cli.eval._judge_gate`)
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
- **Layer:** cli (`dossier.cli.eval`)
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
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier calibrate incident-audit --gold gold/incidents`, 20 of 20 agreed | under `root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini`, the line `                   lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8` |
| 2 | the same | `calibrations/root_cause.json` gains `lower_bound` 0.8389…, `kappa` 1.0, `supported` `{"agreed": 12, "cases": 12}` and `unsupported` `{"agreed": 8, "cases": 8}`; the run gains metrics `judge/root_cause/lower_bound` 83.9, `judge/root_cause/kappa` 1.0, `judge/root_cause/supported` 100.0 and `judge/root_cause/unsupported` 100.0 |
| 3 | a `per_part` pipeline, both samples measured | the same figures for `root_cause.described`, in its own file and under its own metric names (R7.22) |
| 4 | a sample the reviewer marked all supported, 20 of 20 agreed | `kappa not measurable` and `no unsupported case` in the terminal; `kappa` `null` and `unsupported` `{"agreed": 0, "cases": 0}` in the file; no `kappa` or `unsupported` metric |
| 5 | *counter-example* — a `calibrations/root_cause.json` written before R7.26 | loads, and `dossier eval` withholds or reports `root_cause` exactly as before (R7.15); the gate reads the agreement alone |

### R7.30 — `judge.yaml` may declare, per grounding state, the share of unsupported cases a judge must catch

R7.28 reports the two halves of a sample apart, because agreement pools them. A
judge at 90% can have let two invented causes through, and R7.5 compares only
the 90%. Catching an unsupported claim is the judge's whole job (R7.12), so that
half may carry a bar of its own.

It goes where every bar goes: in `gold/<name>/judge.yaml`, agreed by a person,
never in the field declaration (R7.13). It is declared per grounding state,
because a text judge and a page judge are two judges (R7.20), and it is optional.
A state's scalar still means its agreement bar, so every file written before
this rule loads unchanged and declares no unsupported bar.

For `root_cause`, the bar agreed by `a.aleks` on 2026-09-26 is 0.875: out of
R7.11's eight unsupported cases, no more than one let through. It is written as
a share rather than a count, so a sample of forty unsupported cases is held to
the same rate and not to "at most one".

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load.load_judge_thresholds`)
- **Proved by:** `tests/unit/test_R007_30__a_state_may_declare_an_unsupported_bar.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause: {grounded: {agreement: 0.95, unsupported: 0.875}}` | both bars read for `grounded` |
| 2 | `root_cause: {grounded: 0.95, described: {agreement: 0.90, unsupported: 0.875}}` | `grounded` has an agreement bar only; `described` has both |
| 3 | `root_cause: 0.95`, a scalar | the agreement bar for `grounded`, and no unsupported bar; the file loads as it did (R7.20 row 2) |
| 4 | `{grounded: {agreement: 0.95, unsupported: 87.5}}` | load-time error naming the field, the state and `unsupported`; a proportion is a proportion (R7.13 row 3) |
| 5 | `{grounded: {agreement: 0.95, supported: 0.9}}` | load-time error naming `supported` and the two bars that exist; a bar under a name nothing reads gates nothing |
| 6 | *counter-example* — `{grounded: {unsupported: 0.875}}` | load-time error: a state declares its agreement bar, and the unsupported bar is in addition to it, never instead |

### R7.31 — a judged field is withheld when its judge caught fewer of the unsupported cases than the bar asks

With an unsupported bar declared, a state's calibration is compared on that half
as well as on its agreement. The share caught must be at or above the bar. The
bound is inclusive, as R7.5's is: 7 of 8 meets 0.875.

The half must hold at least 8 cases, the number in R7.11's sample, before the
share means anything. Below that, the field is withheld as not measurable, as
R7.11 row 3 treats an agreement over fewer than 20 cases. 1 of 1 is 100%, and it
shows nothing. A calibration from before R7.26 has no counts, so it has nothing
to compare and is withheld until it is measured again.

A withheld field names the state, the count, the share and the bar. "Below the
bar" is not enough here: the fix is a better judge, or more unsupported cases in
the sample, and the message has to say which.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.judges.withholding`)
- **Proved by:** `tests/unit/test_R007_31__a_judge_that_lets_claims_through_is_withheld.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | unsupported bar 0.875, a calibration at 95.0% against 0.95 with unsupported 7 of 8 | reported; 7 of 8 is exactly the bar |
| 2 | exercise 10's described judge: 90.0% against 0.90, unsupported 6 of 8, bar 0.875 | withheld: `unsupported 6 of 8 (75.0%) is below the agreed 87.5%`; its agreement cleared its bar, and it still lets claims through |
| 3 | bar 0.875, a sample holding 7 unsupported cases, all caught | withheld, naming the 7 and the 8 it needs; not measurable, never 100% |
| 4 | bar 0.875, a calibration file written before R7.26 | withheld: measured before its unsupported cases were counted -- run `dossier calibrate` |
| 5 | bar declared, agreement below its own bar | withheld on the agreement, as today; R7.15's order holds, with the unsupported half checked after it |
| 6 | *counter-example* — no unsupported bar declared | gated on the agreement alone, exactly as before (R7.5) |

### R7.32 — a `per_group` step's answers are scored per group, against the gold answer whose `document` is the group

The question was asked of the contract, so the answer is verified for the
contract: `gold/contracts/ACME-2024.json` says `"document": "ACME-2024"`, and gold
is already matched by that field rather than by the file's name. Which member a
value was cited from does not decide whether it is right; that is grounding's
question (R7.4), and a value grounded in amendment 3 that matches the verified date
is correct.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.score_run`), cli (`dossier.cli.eval`)
- **Proved by:** `tests/unit/test_R007_32__a_group_is_scored_against_its_own_gold_answer.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gold/contracts/ACME-2024.json` with `"document": "ACME-2024"` and `renewal_date` `2027-03-31` | scored against `extract/ACME-2024.json`; `renewal_date` correct, grounded in `ACME-2024/amendment-3.pdf` |
| 2 | gold for both contracts | the eval's first line counts `2 groups`, not the four documents the run read |
| 3 | *counter-example* — a gold file whose `document` is `ACME-2024/master.pdf` | not scored: the run answered for the group, and no answer is filed under a member |

### R7.33 — a judged `per_group` field is put to the judge with every member of its group

The judge is asked whether an answer is supported by its evidence, and the
evidence of a group's answer is the group. The stage read every member, and a claim
may stand on two of them: the master's right to terminate on notice, with the date
amendment 3 set. Shown only the member the field cites, the judge would weigh half
the evidence and could call a supported claim unsupported, a mistake its
calibration never measured. So it is shown the group as the stage was, every member
under its own key in key order, as R7.21 shows a described field's judge the pages.
Its verdict is keyed on all of them (R7.18), so a member added or changed asks it
again. A calibration case for such a field names the group as its `document`, and
is judged the same way.

Decided 2026-09-27 by the project owner, over showing the cited member alone.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.judge_scores`, `dossier.application.eval.calibrate_field`)
- **Proved by:** `tests/unit/test_R007_33__a_group_field_is_judged_against_every_member.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `termination_terms` on `ACME-2024`, citing `ACME-2024/amendment-3.pdf` | the judge prompt holds all three members, each under its own key, in key order |
| 2 | the same field after a run in which `ACME-2024` has four members | a different verdict key, and the judge is asked again (R7.18) |
| 3 | a calibration case whose `document` is `ACME-2024` | judged against the three members, as row 1 |
| 4 | *counter-example* — a judged field in a `per_file` step | shown its one document, as before (R7.17) |

### R7.34 — a judged field of a step that reads `reference` is put to the judge with every reference document beside the evidence it was answered from

R7.33's reasoning, with context in place of a group. The judge is asked whether
an answer is supported by its evidence, and a step that reads `reference` answers
from its document and the reference documents together (R3.18). A claim may
stand on both: "escalation came 40 minutes late" needs the incident's timeline
and the 30 minutes `OPS-114` allows. Shown the incident alone, the judge would
call a supported claim unsupported, a mistake its calibration never measured.

So the judge is shown what the stage was shown. First the evidence R7.17, R7.21
or R7.33 gives it: the document, the pages or the group. Then every reference
document, each under its own key, in key order. Its verdict is keyed on all of
them (R7.18), so a procedure edited asks it again. A calibration case for such a
field is judged the same way.

Decided 2026-09-27 by the project owner, over leaving the reference documents
out of the judge's evidence.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval`), cli (`dossier.cli.eval`, `dossier.cli.calibrate`)
- **Proved by:** `tests/unit/test_R007_34__a_field_that_read_reference_is_judged_with_it.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause` on `INC-4821` in `verify`, which reads `reference` holding `OPS-114` | the judge prompt holds `INC-4821` and `OPS-114`, each under its own key |
| 2 | the same field after `OPS-114` moved to `v38` and the run was made again | a different verdict key, and the judge is asked again (R7.18) |
| 3 | a calibration case for that field, naming `INC-4821` | judged against `INC-4821` and `OPS-114`, as row 1 |
| 4 | a `described` field of a step reading `reference` | shown the pages as R7.21 shows them, then `OPS-114` under its own key; a different `OPS-114` is a different verdict key |
| 5 | *counter-example* — a judged field of `extract`, which reads `documents` only | shown its one document, as before (R7.17) |

### R7.35 — `--compare` refuses two runs shown different reference documents, by key or by snapshot

R7.8 refuses a comparison over different documents, because a field can move
with its documents and the delta would credit the configuration with it. A
procedure moves a field just as surely: `escalation_limit` is read out of
`OPS-114`, and tightened from 30 minutes to 15 it moves every answer that cites
it. So two runs whose calls were shown different reference documents are not
compared. By snapshot as well as by key, because a procedure tightened in
place keeps its key, and that is the usual way a procedure changes. To compare
two configurations fairly, run the earlier one again over today's procedures;
everything that did not read them is served from the cache.

What was *shown* is the test, so the check reads what each run's steps read.
A pipeline that declares `reference:` and has no step reading it showed no call
anything, and its runs compare as R7.8 says.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.check_same_reference`) plus cli (`dossier eval --compare`)
- **Proved by:** `tests/unit/test_R007_35__compare_refuses_runs_shown_different_reference.py`, `tests/acceptance/test_R007_35__eval_compare_refuses_a_run_whose_procedure_moved.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `verify` reads `reference`; run `b` was shown `OPS-114` at a new snapshot | an error, exit 2: `runs a and b were shown different reference documents -- OPS-114 changed. A field can move because its context did.` |
| 2 | run `b` was shown `OPS-116` as well, which run `a` was not | the same error, naming `only in b: OPS-116` |
| 3 | *counter-example* — the same reference keys at the same snapshots, the prompt edited between `a` and `b` | compared, as R7.8 row 1 |
| 4 | *counter-example* — a pipeline with no `reference:` at all | compared; there is nothing to differ |
| 5 | *counter-example* — `reference:` declared, `OPS-114` moved between `a` and `b`, and no step of either run reads `reference` | compared; no call was shown it |

### R7.36 — a `boolean` field is correct when the run and gold hold the same truth value

`true` and `false`, or the strings `"true"` and `"false"` in any case. Anything
else is not a well-formed boolean, and is reported as unreadable rather than as
a mismatch, as a malformed date is. Values are from `_fixtures.md`'s "Fields on
the contracts".

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.score_field`)
- **Proved by:** `tests/unit/test_R007_36__a_boolean_is_scored_by_its_truth_value.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `ACME-2024`'s `auto_renew` `true`, grounded, against gold `true` | correct |
| 2 | `GLOBEX-2023`'s `auto_renew` `false`, grounded, against gold `false` | correct; `false` is an answer, not an abstention, and is not scored as one |
| 3 | `auto_renew` `"True"`, a string, against gold `true` | correct; whether the model quoted the value is not information |
| 4 | `auto_renew` `false` against gold `true` | incorrect; the detail says `False` does not match `True` |
| 5 | *counter-example* — `auto_renew` `1` against gold `true` | incorrect, reported as not a well-formed boolean; `1` is a number |
| 6 | *counter-example* — `auto_renew` `"yes"` against gold `true` | incorrect, reported as not a well-formed boolean; `yes` is a word |
| 7 | *counter-example* — `INITECH-2025`'s gold `auto_renew: null`, the run answering `false` with a grounded span | incorrect; the contract not saying so is not `false` (R7.3 row 2) |

### R7.37 — a `duration` is a whole number of days, weeks, months or years, and nothing else is a duration

Written `<number> <unit>`, singular or plural, in any case, or as ISO 8601 with
one component. A value that is not one is unreadable, reported as not a
well-formed duration rather than as a mismatch.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.score_field`)
- **Proved by:** `tests/unit/test_R007_37__a_duration_names_its_unit.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `ACME-2024`'s `notice_period` `"90 days"` against gold `"90 days"` | correct; read as 90 days |
| 2 | `notice_period` `"P90D"` against gold `"90 days"` | correct; ISO 8601's form of the same length |
| 3 | `notice_period` `"1 Year"` against gold `"1 year"` | correct; singular, and case folded |
| 4 | *counter-example* — `notice_period` `90`, a bare number, against gold `"90 days"` | incorrect, reported as not a well-formed duration; ninety of what is not said, and is not guessed |
| 5 | *counter-example* — `notice_period` `"90 business days"` against gold `"90 days"` | incorrect, reported as not a well-formed duration; a business day's length depends on a calendar |
| 6 | *counter-example* — `notice_period` `"P1Y6M"` against gold `"18 months"` | incorrect, reported as not a well-formed duration; one number and one unit, and `18 months` is how to say it |

### R7.38 — two durations are the same answer when they are the same length, and a month is never a number of days

A week is seven days and a year is twelve months, exactly, so those convert. A
month is 28 to 31 days and a year 365 or 366, so nothing converts between days
or weeks and months or years, and a pair across that line is a mismatch whose
detail says so.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.score_field`)
- **Proved by:** `tests/unit/test_R007_38__durations_are_compared_by_length.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `notice_period` `"12 weeks"` against gold `"84 days"` | correct; a week is exactly seven days |
| 2 | `notice_period` `"24 months"` against gold `"2 years"` | correct; a year is exactly twelve months |
| 3 | `notice_period` `"13 weeks"` against gold `"90 days"` | incorrect; 91 days is not 90 |
| 4 | *counter-example* — `GLOBEX-2023`'s `notice_period` `"90 days"` against gold `"3 months"` | incorrect; the detail says a month is not a fixed number of days, so the two are not compared as lengths |
| 5 | *counter-example* — `notice_period` `"1 year"` against gold `"365 days"` | incorrect, for the same reason: a year is not a fixed number of days |

### R7.39 — `dossier eval` scores a `boolean` and a `duration` field per field, beside the others

What a person running the contract audit sees: the two fields listed with their
own percentages (R7.2), and a miss named with the reason R7.38 gave (R7.25).

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.eval`)
- **Proved by:** `tests/acceptance/test_R007_39__eval_scores_a_boolean_and_a_duration.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `schemas/contract.yaml` declaring `auto_renew: {kind: boolean}` and `notice_period: {kind: duration}`; gold for `ACME-2024` and `GLOBEX-2023` as `_fixtures.md` has it; a run answering `auto_renew` `true` and `false`, and `notice_period` `90 days` for both | `auto_renew 100.0%` and `notice_period 50.0%`, each on its own line |
| 2 | the same | under `notice_period`, `GLOBEX-2023` is named with the detail that `90 days` does not match `3 months` and that a month is not a fixed number of days |
| 3 | *counter-example* — `schemas/contract.yaml` declaring `notice_days: {kind: number}` | a load-time error naming `notice_days` and the kinds there are, `boolean` and `duration` among them; a count is an `amount` with no `currency` |

### R7.40 — a `list` field is correct when the run's items and gold's items are the same set

Order, case and repetition are not information. An item is compared as text with
its case folded and its surrounding whitespace trimmed, and it matches whole. The
values are `_fixtures.md`'s "A list field".

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`)
- **Proved by:** `tests/unit/test_R007_40__a_list_is_scored_as_a_set.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `affected_systems` on `INC-4821` answered `payments-api` and `ledger-batch`, against gold `["payments-api", "ledger-batch"]` | correct |
| 2 | answered `ledger-batch` and `Payments-API` | correct; order and case are not information |
| 3 | `payments-api` answered on two pages, and `ledger-batch` | correct; one system named twice is one system |
| 4 | `payments-api` alone | incorrect, `missing: ledger-batch` |
| 5 | `payments-api`, `ledger-batch` and `upload-service` | incorrect, `not in gold: upload-service` |
| 6 | *counter-example* — `payments` against gold `["payments-api"]` | incorrect; an item matches whole, never as part of another |
| 7 | *counter-example* — the run abstains, and gold is `null` | correct, as for any field; an abstention is not an empty list (R7.3) |

### R7.41 — a `list` field is one verdict per document, however many records answered it

A field's percentage counts documents (R7.2). A list counted per item would
weigh a document by how many systems it names, and one incident with nine
systems would outvote eight incidents with one.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`)
- **Proved by:** `tests/unit/test_R007_41__a_list_is_one_verdict_per_document.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821` answered by two records, both in gold | `affected_systems` scored 1 of 1 for `INC-4821`, not 2 of 2 |
| 2 | one item in gold and one not | one incorrect verdict, not one correct and one incorrect |
| 3 | *counter-example* — a gold file with no `affected_systems` entry | no verdict for that document, rather than a zero (R7.3 row 4) |

### R7.42 — an ungrounded item makes its list incorrect, even when every value matches gold

R7.4 for each item. An item's record is checked as any record is (spec 006), and
one that fails its check fails the list.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`)
- **Proved by:** `tests/unit/test_R007_42__an_ungrounded_item_fails_its_list.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `payments-api` grounded, and `ledger-batch` with a span not found in `INC-4821` | incorrect, `ungrounded: ledger-batch` (R7.4) |
| 2 | an item on `INC-4821` citing `INC-4822` | incorrect; the item is invalid (R6.23) |
| 3 | *counter-example* — a record abstaining with a reason, beside `payments-api` and `ledger-batch`, both grounded | correct; an abstention is not a failure (R6.5), and the list is its items |

### R7.43 — a `list` field's item precision and recall are printed and recorded beside its percentage, and gate nothing

Precision is, of the items the run named, how many gold names; recall is, of
gold's items, how many the run named. Each is summed over the documents scored.
An item whose record failed its check counts as named and never as matched. The
same figures go to the terminal and to MLflow, which is a second place to read a
figure and never a second way of arriving at one (spec 011).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`), application (`dossier.application.eval`), cli (`dossier.cli.eval`)
- **Proved by:** `tests/unit/test_R007_43__a_list_reports_item_precision_and_recall.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the list example | `affected_systems  50.0%   items: precision 75.0% (3/4), recall 60.0% (3/5)`; and `precision/affected_systems` 75.0 and `recall/affected_systems` 60.0 recorded beside `accuracy/affected_systems` 50.0 (R11.3) |
| 2 | gold `null` for `INC-4822`, and the run names `ledger-batch` | one item named and none matched: precision falls, recall is unchanged |
| 3 | *counter-example* — `--compare` of two runs at the same percentage, the second's precision lower | not a regression; R7.8 gates on the percentage alone |
| 4 | *counter-example* — a run that abstains on every document | `precision --`, not 0.0%: nothing was named, so nothing named was wrong |

### R7.44 — gold for a `list` field is a non-empty array of strings, and only a `list` field holds one

Refused when `dossier eval` reads the gold set, before anything is scored: a
gold answer in the wrong shape is a definition of correct nobody can meet.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring`), application (`dossier.application.eval`)
- **Proved by:** `tests/unit/test_R007_44__a_list_in_gold_is_an_array.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `{"value": ["payments-api", "ledger-batch"]}` for `affected_systems: {kind: list}` | two items |
| 2 | `{"value": null, "reason": "not stated in document"}` | a verified abstention, as for any field (R7.3) |
| 3 | *counter-example* — `{"value": "payments-api, ledger-batch"}` | refused, naming `INC-4821` and `affected_systems` and saying a list is written as an array; not split on the comma, which an item may hold |
| 4 | *counter-example* — `{"value": []}` | refused, naming `null` with a reason as what to write instead |
| 5 | *counter-example* — `{"value": ["major"]}` for `severity: {kind: enum}` | refused, naming `severity`; only a `list` field holds an array |

### R7.45 — `dossier eval` scores a `list` field per field, beside the others

What a person auditing incidents sees once `affected_systems` is declared a
list: its own percentage (R7.2), what the items say beside it (R7.43), and each
miss named with what was missing and what was not in gold (R7.25).

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.eval`)
- **Proved by:** `tests/acceptance/test_R007_45__eval_scores_a_list_field.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `schemas/incident.yaml` declaring `severity: {kind: enum}` and `affected_systems: {kind: list}`; gold and a run as `_fixtures.md`'s "A list field" has them | `severity 100.0%` and `affected_systems 50.0%` with its items line, each on its own line; four model calls, all made by `run` (R7.10) |
| 2 | the same | under `affected_systems`, `INC-4821` named with `missing: ledger-batch`, and `INC-5455` with `missing: upload-service` and `not in gold: payments-api` |
| 3 | *counter-example* — `gold/incidents/INC-4821.json` holding `affected_systems` as `"payments-api, ledger-batch"` | exit code 2 naming `INC-4821` and `affected_systems`, before any score is printed (R7.44) |

### R7.46 — a field a `per_part` step answers is one verdict per document, however many of its pages answered it

A field's percentage counts documents (R7.41). Counted per page, `INC-4830`'s
three pages would outvote a one-page document three to one on every field its
header carries. The values are `_fixtures.md`'s "`INC-4830` page by page".

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.score_document`), application (`dossier.application.eval.score_run`)
- **Proved by:** `tests/unit/test_R007_46__a_per_part_field_is_one_verdict_per_document.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `severity` on `INC-4830`, answered `critical` on each of its three pages from the header each prints, against gold `critical` | 1 of 1 for `INC-4830`, not 3 of 3 |
| 2 | `INC-4830` and `INC-5720-checkout-latency-postmortem.png`, a picture of one page, each answering `severity` as gold does | `severity` scored 2 of 2: a document weighs one, however many pages it has |
| 3 | *counter-example* — `severity` from a `per_file` step, one record per document | one verdict per document, as before; there is one answer and nothing to combine |

### R7.47 — a page that abstains does not answer for its document while another of its pages gives a value

"Not on this page" is a fact about the page, not about the document. The
document abstains only when every page did, and is then scored as any abstention
is (R7.3).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.score_document`)
- **Proved by:** `tests/unit/test_R007_47__a_page_that_abstains_does_not_answer_for_its_document.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `resolution_date` `2026-07-28` on `INC-4830`'s page 1, pages 2 and 3 abstaining with the reason `not on this page`, against gold `2026-07-28` | correct. Before this rule, 1 of 3 |
| 2 | every page abstaining, against a gold `null` | correct: the document abstains, and so does gold (R7.3 row 1) |
| 3 | *counter-example* — every page abstaining, against gold `2026-07-28` | incorrect, `abstained on every page; gold states '2026-07-28'`: when every page abstains, the abstention is the document's answer (R7.3 row 3) |

### R7.48 — a field is correct only when every page that gave it a value is correct, and the detail names each page that was not

Each page's value is scored as a `per_file` step's record is: grounded (R7.4),
then compared with gold by its kind. Each page is held to gold and never to the
other pages, so two pages spelling one answer differently agree. A page is named
as the part it came from (R8.11).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.score_document`), application (`dossier.application.eval.score_run`)
- **Proved by:** `tests/unit/test_R007_48__every_page_that_answers_must_be_correct.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `resolution_date` `2026-07-28` on `INC-4830`'s page 1 and `2026-07-30` on page 2, the day the postmortem review was held, against gold `2026-07-28` | incorrect, `page-002.png: '2026-07-30' does not match '2026-07-28'` |
| 2 | `loss_amount` `48200.00` CHF on page 1, grounded, and `48200.00` CHF on page 3 with a span not found in `INC-4830` | incorrect, `page-003.png: ungrounded` (R7.4); a right value on one page does not vouch for a page with no evidence |
| 3 | `severity` `critical` on pages 1 and 2, and `Critical` on page 3 | correct; each page matches gold with its case folded, as an enum is compared |
| 4 | *counter-example* — `affected_systems` on `INC-4821`, `payments-api` named on one page and `ledger-batch` on another, against gold `["payments-api", "ledger-batch"]` | correct, one set (R7.40 row 3); a list's items on different pages are its items, not a disagreement |

### R7.49 — a judged field is put to the judge once for each page that gave it a value, and is correct only when the judge supports every one

The judge is asked about the run's answer (R7.17), and a document read page by
page gives one answer per page. Each page's value is judged against the evidence
R7.17, R7.21 or R7.34 gives it: the document's text for a page whose span was
found in it, the document's pages for a page that is `described`. Each is a
verdict key of its own (R7.18). A page whose value fails without a judge --
ungrounded (R7.4), or citing a document its call was not shown (R6.23) -- fails
the field before the judge is asked, so the judge is asked only about a field
every page can still get right. The candidates are `_fixtures.md`'s `rc-01`,
supported, and `rc-02`, the planted claim.

- **Kind:** deterministic
- **Layer:** application (`dossier.application.eval.judge_scores`), domain (`dossier.domain.scoring.with_judged`)
- **Proved by:** `tests/unit/test_R007_49__each_pages_judged_value_must_be_supported.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `root_cause` on the photocopied `INC-4830`, page 2 answering `rc-01`'s words, pages 1 and 3 abstaining | one judge call, shown the three pages (R7.21); supported, so correct |
| 2 | page 2 answering `rc-02`'s words and page 3 `rc-01`'s | two judge calls; incorrect, naming `page-002.png` and the judge's evidence. Before this rule only the last page's answer was judged, and its verdict was given to page 2's as well |
| 3 | pages 2 and 3 both answering `rc-01`'s words | one judge call: the same candidate on the same evidence is the same key (R7.18), and the second is served from cache |
| 4 | the half-photocopied `INC-4830`, `rc-01`'s words on page 1, their span found in its text layer, and on page 2, a picture | two judge calls: page 1's against the document's text (R7.17), page 2's against its pages (R7.21). The same words on different evidence are two keys |
| 5 | page 2 answering `rc-01`'s words, and page 3 a value citing `INC-4821` | incorrect (R6.23), and no judge call: nothing the judge says could make the field correct |
| 6 | *counter-example* — `root_cause` from a `per_file` step | one value and one judge call, as R7.17 has always asked |

### R7.50 — a declared field gold verifies and the run gave no record for is scored as an abstention, and named `not answered`

In every mode. Only a field the step declares: a field the step was never asked
for is not one it failed to answer. Named apart from `abstained`, because a
person reading the miss needs to know the run said nothing at all, not that it
said the document is silent.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.scoring.score_document`)
- **Proved by:** `tests/unit/test_R007_50__a_field_never_answered_is_scored_as_an_abstention.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `extract` in `per_file` mode answering `INC-4821` with no `loss_amount` record, against gold `48200.00` CHF | incorrect, `not answered; gold states 48200.0`. Before this rule, no verdict, and `loss_amount`'s percentage counted only the documents that answered it |
| 2 | `INC-4821` answered with no `root_cause` record, against gold `null` | correct, as an abstention against a gold `null` is (R7.3 row 1) |
| 3 | `INC-4830` read `per_part`, no page giving `root_cause`, against gold's `the renewed TLS certificate was never deployed to the load balancers` | incorrect, `not answered`, and no judge call: there is no candidate to judge |
| 4 | *counter-example* — gold holding `root_cause` for a step whose declaration has no `root_cause` | no verdict; the step was never asked for it |
| 5 | *counter-example* — a gold file with no `loss_amount` entry, and no `loss_amount` record | no verdict (R7.3 row 4); nobody verified an answer to score against |
| 6 | *counter-example* — `INC-4822`, a document the step failed on after its retry | not scored (R6.9); a failed document is reported as failed, not as one that answered nothing |

### R7.51 — `dossier eval` scores a `per_part` step's fields once per document

What a person auditing postmortems page by page sees: each field counted over
documents, and the page that got one wrong named under it (R7.25).

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.eval`)
- **Proved by:** `tests/acceptance/test_R007_51__eval_scores_a_per_part_field_once_per_document.py`
- **Status:** IN PROGRESS

| # | Given | Then |
|---|-------|------|
| 1 | `extract` in `per_part` mode reading `documents@page_images`, declaring `severity` and `resolution_date` alone, over `INC-4830` and `INC-5720-checkout-latency-postmortem.png`. `INC-4830`'s three pages each answer `severity` `critical`, page 1 answers `resolution_date` `2026-07-28` and page 2 `2026-07-30`; `INC-5720`'s one page answers `major` and `2026-09-02`. Gold as `_fixtures.md` has them | `2 documents · 2 fields · overall 75.0%`, `severity 100.0%` and `resolution_date 50.0%`; four model calls, all made by `run` (R7.10) |
| 2 | the same | under `resolution_date`, `INC-4830` named with `page-002.png: '2026-07-30' does not match '2026-07-28'` (R7.25) |
| 3 | the same | `accuracy/severity` 100.0 and `accuracy/resolution_date` 50.0 recorded to MLflow (R11.3), the figures the terminal printed |
| 4 | *counter-example* — `INC-4830`'s gold file holding no `resolution_date` | `resolution_date 100.0%`, scored on `INC-5720` alone; page 2's date is not named, because nobody verified the answer it disagrees with (R7.3 row 4) |
