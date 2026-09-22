---
name: eval
model: claude-opus-5-5
allowed-tools: Read, Write, Edit, Bash, AskUserQuestion
description: Build or run the check for an `evaluated` spec rule - the non-deterministic half of the workflow. Use when a rule cannot be asserted with == (judge agreement, narrative quality) and needs a scored threshold instead. Counterpart to /tdd.
argument-hint: "<rule id> [spec file] | --run"
---

Handle the eval side of: $ARGUMENTS

`/tdd` proves `deterministic` rules exactly. This proves `evaluated` rules against a
threshold agreed in the spec. It is the only place in this project where a real model
call is allowed in a test.

There are currently **two** such rules in the whole repository — R7.11 and R7.12 — out
of seventy-one. That ratio is the design working, not a gap. Guard it.

## Mode A — build the check for a rule

### 1. Confirm the rule is genuinely evaluated

Read its `**Kind:**` line.

- `deterministic` — stop. It belongs in `/tdd`.
- `evaluated` — try **once more** to split it, using
  `../discover/references/splitting-rules.md`. Every rule moved out of eval-land
  becomes fast, free and exact. Report what you split; that is the real win.
- Missing — the spec is unfinished. Send the user back to `/discover`.

Spec 007 is the worked example of that split: "prove the audit is correct" became ten
deterministic rules and two evaluated ones. Before you accept a third, check it is not
a decision in disguise — R7.4 ("an ungrounded field is incorrect even when its value
matches gold") sounds like a quality judgement and is a string search.

### 2. Pick the metric — cheap and objective before an LLM judge

| Claim | Metric | Cost |
|---|---|---|
| the output parses / conforms to its schema | parse success rate | free, exact |
| the span occurs in the source text | string search | free, exact (R6.4) |
| a value matches the gold set after normalisation | exact match | free, exact (R7.1) |
| a boolean verdict is correct on labelled cases | accuracy against labels | free once labelled |
| the judge returns the right verdict on a planted flaw | pass/fail on that case | one model call |
| the judge agrees with human scorers | agreement over a sample | paid, noisy |
| the narrative summary is good | LLM-judge rubric | paid, noisy, hardest to trust |

Reach for an LLM judge only when nothing objective expresses the claim. In `dossier`
most of the audit is checkable without one, and that is stated as a product claim in
spec 007 — "the model judge is the exception, not the method."

When you do use one: give it a rubric with explicit scoring anchors, `temperature=0`,
and **check the judge against human-labelled cases before trusting it** (R7.5, R7.6).
An unvalidated judge is a random number generator with good manners. A judge that
agrees with everything is indistinguishable from no judge — which is exactly why R7.12
exists as a separate rule.

### 3. Build the dataset

`tests/evals/golden/<name>.jsonl`, one case per line, stable `id` per case.

**Below about 20 cases a threshold means nothing** — the noise exceeds the signal and
you are measuring the sampler, not the system. R7.11 says this in the spec itself and
records the threshold as OPEN for that reason. Say "not measurable at this N" rather
than quoting a percentage off three cases.

Cover the happy path, every counter-example in the spec, and the known hard cases.
Record where each came from (`"source": "INC-4821, reviewed by a.muster"`) so a later
reader can judge whether the set is representative.

**You cannot write to `tests/evals/golden/` or `gold/` — the hook blocks it.**
Deliberate. The failure mode of eval-driven work is quietly editing the expected answer
until the eval passes, and R7.7 says corrections into the gold set are attributed to a
human. Prepare the cases, show them, let the user write the file.

### 4. Write the check

Named for the rule like every other test, and marked `live` so it stays out of the
default suite:

```python
@pytest.mark.live
class TestJudgeDetectsPlantedClaim:
    """R7.12 — the judge marks a planted unsupported claim as unsupported.

    Threshold: pass on the planted case, every run. Sample: see the rule.
    """
```

Assert the **verdict**, never the wording of the rationale — R7.12's own example table
says so. Record the model id with any score: a number without the model that produced
it is not reproducible, and R7.6 makes a stale calibration an error.

## Mode B — run them (`--run`)

```bash
uv run pytest -m live -q
```

Report a table: rule id, metric, score, N, threshold, pass/fail, and the model id used.

**On a failure, diagnose before touching anything**, in this order:

1. Did the **rubric** change? Most likely cause. Diff the judge instructions — and note
   that under R7.6 a rubric change makes the existing calibration stale, which is an
   error rather than a warning.
2. Did the **model or its version** change? Second most likely and invisible in a diff.
   The pin is in `pipeline.yaml` and R0.6 forbids aliases, so a silent re-point should
   be impossible — verify that it was.
3. Did the **converted document** change? A converter version bump re-converts
   everything (R5.4), and the judge is now reading different text.
4. Is the **case** wrong — mislabelled, or no longer reflecting the rule?

Only (4) justifies changing the data, and only the user can make that change.

**Never propose lowering a threshold to get green.** If the threshold is genuinely
wrong, say so, give the evidence, and let the user decide. A lowered threshold is a
product decision, not a test fix — and under R7.5 it is the difference between a judge
that may be reported and one that may not.

## Report

- The rule, its metric, its threshold, and **who agreed the threshold**.
- The score, N, and the model id.
- Pass or fail; for a failure, the ranked diagnosis above.
- Any deterministic rules you split out along the way — lead with these.
