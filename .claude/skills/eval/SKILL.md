---
name: eval
model: claude-opus-5
allowed-tools: Read, Write, Edit, Bash, AskUserQuestion
description: Build or run the check for an `evaluated` spec rule - the non-deterministic half of the workflow. Use when a rule cannot be asserted with == (groundedness, summary quality, tone) and needs a scored threshold instead. Counterpart to /tdd.
argument-hint: "<rule id> <spec file> | --run"
---

Handle the eval side of: $ARGUMENTS

`/tdd` proves `deterministic` rules exactly. This proves `evaluated` rules against a
threshold agreed in the spec. It is the only place in this project where a real model
call is allowed in a test.

## Mode A — build the check for a rule

### 1. Confirm the rule is genuinely evaluated

Read its `**Kind:**` line.

- `deterministic` — stop. It belongs in `/tdd`.
- `evaluated` — try **once more** to split it, using
  `../discover/references/splitting-rules.md`. Every rule moved out of eval-land
  becomes fast, free and exact. Report what you split; that is the real win.
- Missing — the spec is unfinished. Send the user back to `/discover`.

### 2. Pick the metric — cheap and objective before an LLM judge

| Claim | Metric | Cost |
|---|---|---|
| the output parses / conforms to a type | parse success rate | free, exact |
| the output is the right length | p50/p90 token count | free |
| a boolean verdict is correct on labelled cases | accuracy against labels | free once labelled |
| the judge returns the right verdict on a planted flaw | pass/fail on that case | one model call |
| the answer is grounded in its source | LLM-judge groundedness | paid, noisy |
| the summary is good | LLM-judge rubric | paid, noisy, hardest to trust |

Reach for an LLM judge only when nothing objective expresses the claim.

When you do: give it a rubric with explicit scoring anchors, `temperature=0`, and
**check the judge against human-labelled cases before trusting it**. An unvalidated
judge is a random number generator with good manners.

That is not hypothetical here. `qwen2.5-coder:1.5b-base` scored a summary containing a
planted hallucination as grounded; `llama3.2:3b` gave that same summary 5/5 on
`summary_quality` while its own groundedness judge failed it. A judge that agrees with
everything is indistinguishable from no judge.

### 3. Build the dataset

`tests/evals/golden/<name>.jsonl`, one case per line, stable `id` per case.

**Below about 20 cases a threshold means nothing** — the noise exceeds the signal and
you are measuring the sampler, not the system. This project currently has **one**
sample case, which is enough to detect a judge that has stopped working and not enough
to measure one. Say so rather than quoting a percentage off a single case.

Cover the happy path, every counter-example in the spec, and the known hard cases.
Record where each came from (`"source": "trace tr-21acde…"`) so a later reader can
judge whether the set is representative.

**You cannot write to `tests/evals/golden/` — the hook blocks it.** Deliberate. The
failure mode of eval-driven work is quietly editing the expected answer until the eval
passes. Prepare the cases, show them, let the user write the file.

### 4. Write the check

Marked `live` so it stays out of the default suite:

```python
@pytest.mark.live
class TestGroundednessCatchesHallucination:
    """004 R8 — a judge detects a claim absent from the source.

    Threshold: must return False on the built-in sample, every run.
    """
```

Assert the **verdict**, never the wording of the rationale. Record the model id with
any score: a number without the model that produced it is not reproducible.

## Mode B — run them (`--run`)

```bash
uv run pytest -m live -q
```

Report a table: rule id, metric, score, threshold, pass/fail, and the model id used.

**On a failure, diagnose before touching anything**, in this order:

1. Did the **prompt** change? Most likely cause. Diff the judge instructions.
2. Did the **model or its version** change? Second most likely and invisible in a diff
   — check `JUDGE_GATEWAY_MODEL` and what the gateway endpoint actually points at.
3. Did the **gateway** change — endpoint repointed, base URL, provider swapped?
4. Is the **case** wrong — mislabelled, or no longer reflecting the rule?

Only (4) justifies changing the data, and only the user can make that change.

**Never propose lowering a threshold to get green.** If the threshold is genuinely
wrong, say so, give the evidence, and let the user decide. A lowered threshold is a
product decision, not a test fix.

## Report

- The rule, its metric, its threshold, and who agreed the threshold.
- The score, N, and the model id.
- Pass or fail; for a failure, the ranked diagnosis above.
- Any deterministic rules you split out along the way — lead with these.
