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
"The answer cites its source" splits into *a citation exists and resolves to a chunk
that was actually retrieved* (deterministic) and *the cited source supports the claim*
(evaluated).

**Shape vs. content.**
"Returns a useful summary" splits into *conforms to the schema, non-empty, within
length bounds* (deterministic) and *captures the key points* (evaluated).

**Trigger vs. output.**
"Escalates angry customers" splits into *escalates when the sentiment score is below
the threshold* (deterministic, given a score) and *sentiment scoring is accurate*
(evaluated, on a labelled set).

**Policy vs. prose.**
"Never gives medical advice" splits into *the refusal path fires for flagged intents*
(deterministic) and *intent classification catches paraphrases* (evaluated).

## Worked example from this repository

The request was: *"score the traces so I can see quality regressions."* Unfalsifiable
as stated. It became:

| Rule | Kind | Proved by |
|---|---|---|
| Only `gateway:/...` is eligible for automatic scoring | deterministic | unit test |
| A model pinned for one provider must not repoint another's endpoint | deterministic | unit test |
| The sample rate is validated before any judge is touched | deterministic | unit test |
| Judge settings default per provider | deterministic | unit test |
| A keyless provider still gets a secret row | deterministic | unit test |
| A judge whose registered model drifted is re-registered | deterministic | unit test |
| Registering a judge does not start it | deterministic | acceptance test |
| A judge detects a claim absent from the source | **evaluated** | live judge run, threshold |
| The graded judge discriminates good from bad summaries | **evaluated** | threshold OPEN, unmet |

Seven of nine provable in milliseconds with no model. Two need a real run. That ratio
is the goal.

Note what the two survivors have in common: both are judgements about generated text.
Everything else — eligibility, precedence, validity, drift — was a decision, and every
one of those decisions had already caused a real bug precisely because it was buried
next to a model call where nobody could test it.

## Signals to read while mapping

- **More than about eight rules** — the story is too big. Split it before any test.
- **A rule with no example** — it is not understood yet. Ask for one.
- **A rule with no counter-example** — suspicious. Either a truism, or two rules.
- **Many open questions** — do not start building. A wrong assumption costs far more
  than the question.
- **An example needing three paragraphs of setup** — the design is wrong, or the rule
  spans a layer boundary it should not.

## What this is not

- Not Gherkin. The Given/When/Then table is a spec format here, not a discovery ritual.
- Not design. Do not discuss providers, prompt wording or gateway plumbing yet.
- Not test writing. `/accept` does that, one rule at a time, afterwards.
