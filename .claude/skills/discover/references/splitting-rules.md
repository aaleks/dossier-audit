# Splitting a rule across the determinism boundary

The highest-value move in this workflow. A rule that looks `evaluated` is usually a
deterministic decision wrapped around an evaluated judgement — and separating them
converts an unfalsifiable requirement into a fast exact test plus a smaller eval.

## The pattern

> The **decision** is deterministic and belongs in `domain/`.
> The **judgement feeding the decision** is evaluated.

Apply it before accepting any rule as `evaluated`. Try once, honestly. Report what you
split — those are the real wins.

## Four angles

**Presence vs. correctness.**
"Every figure carries its evidence" splits into *the quoted span occurs in the
converted text of a document that was an input to this stage* (deterministic — a string
search, R6.3 and R6.4) and *the cited sentence actually supports the value* (evaluated).

**Shape vs. content.**
"The output is usable" splits into *it validates against the declared schema, every
non-null field has a source, abstention carries a reason* (deterministic, R6.1/R6.5/R6.6)
and *the narrative summary captures the incident* (evaluated).

**Trigger vs. output.**
"Only trustworthy judges are reported" splits into *a judge below its configured
agreement threshold cannot be used as a reported metric* (deterministic given a number,
R7.5) and *what that agreement number actually is* (evaluated, R7.11).

**Policy vs. prose.**
"Re-running is cheap" splits into *an unchanged normalised payload produces no new
snapshot and no fetch* (deterministic, R2.2/R2.5) and nothing evaluated at all — some
requests split entirely into the deterministic column, which is the best outcome.

## Worked example from this repository

The request was: *"prove the audit is correct."* Unfalsifiable as stated. Spec 007
became twelve rules:

| Rule | Kind | Proved by |
|---|---|---|
| R7.1 Non-judge scoring is deterministic | deterministic | unit test |
| R7.2 Results are reported per field, never as one blended figure | deterministic | acceptance test |
| R7.3 A gold null scores abstention correct and a value incorrect | deterministic | unit test |
| R7.4 An ungrounded field is incorrect even when its value matches | deterministic | unit test |
| R7.5 A judge below its threshold cannot be a reported metric | deterministic | unit test |
| R7.6 A stale calibration is an error, not a warning | deterministic | unit test |
| R7.7 Gold corrections are versioned and attributed | deterministic | unit test |
| R7.8 `--compare` scores the same documents and flags regressions | deterministic | acceptance test |
| R7.9 Runs and scores are recorded to MLflow | deterministic | integration test |
| R7.10 Non-judge scoring touches no network | deterministic | unit test |
| R7.11 The judge agrees with human scores on the calibration sample | **evaluated** | threshold OPEN |
| R7.12 The judge marks a planted unsupported claim as unsupported | **evaluated** | threshold OPEN |

Ten of twelve provable in milliseconds with no model. Two need a real run.

Note what the two survivors have in common: both are judgements about generated text.
Everything else — eligibility, staleness, precedence, grounding, attribution — was a
decision. And notice R7.4 in particular: "an ungrounded field is incorrect even when its
value matches gold" sounds like a quality judgement and is a string search.

The same happened in spec 002. "Only fetch what changed" sounds like heuristics; it
came out as five exact rules about version markers, hashes and a time window.

## Signals to read while mapping

- **More than about eight rules** — the story is too big. Split it before any test.
- **A rule with no example** — it is not understood yet. Ask for one.
- **A rule with no counter-example** — suspicious. Either a truism, or two rules.
- **A rule whose Then is "it works"** — ask *how many*. In this project the honest
  answer is usually a count: zero fetches, one retry, 20 of 420 re-run.
- **Many open questions** — do not start building. A wrong assumption costs far more
  than the question.
- **An example needing three paragraphs of setup** — the design is wrong, or the rule
  spans a layer boundary it should not.

## What this is not

- Not Gherkin. The Given/Then table is a spec format here, not a discovery ritual.
- Not design. Do not discuss connectors, prompt wording or storage layout yet.
- Not test writing. `/accept` does that, one rule at a time, afterwards.
