---
name: tdd
model: claude-sonnet-5
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
description: Run ONE TDD inner-loop cycle - red, green, refactor, challenge, stop. Drives a single failing test to green with the minimum code, then proposes the next edge case. Use after /accept. One cycle per invocation.
argument-hint: "<test or behaviour to drive> [--to-green <test>]"
---

Run ONE inner cycle for: $ARGUMENTS — one failing test driven to green, refactored,
then STOP.

**One cycle = one test.** A single new test function, or one new case added to an
existing `parametrize` list. It is *not* "drive until everything passes" — that is the
outer loop. The edge case you propose in CHALLENGE becomes the next RED in a **new**
invocation.

The only exception is run-to-green mode, which the user must request explicitly with
`--to-green`. Never assume it.

## The loop

```
RED  →  GREEN  →  REFACTOR  →  CHALLENGE  →  STOP
```

Do not collapse green and refactor into one step. Getting it working and getting it
right are different problems, and solving both at once is how you end up with neither.

## 1. Confirm red, and why

```bash
uv run pytest tests/unit/test_<x>.py::<Class> -q
```

If it is not red, stop — there is nothing to do here, and something upstream is
wrong. Go back to `/accept`.

## 2. Choose the layer

| The rule is about | Layer | Constraint |
|---|---|---|
| A decision: precedence, validation, eligibility | `domain/` | Imports **nothing**. Takes the environment as an argument, never reads `os.environ`. |
| Loading `.env` | `config/` | The only module that touches `os.environ`. |
| A use case or a prompt | `application/` | No `mlflow`, `langfuse`, `litellm`. Takes the model as an argument. |
| A vendor call | `infrastructure/` | SDK imports go **inside** functions, not at module scope. |
| Flags, banner, exit codes | `cli/` | The only place `sys.exit` is allowed. |

**Default to `domain/`.** If a rule can be expressed as a pure decision, put it
there — that is what makes it testable in milliseconds without a server, and it
is why 92 of this project's tests need no fixtures.

A PreToolUse hook blocks an SDK import in `domain/` at write time. If it fires,
you picked the wrong layer: the decision goes in `domain/`, the call that acts
on it goes in `infrastructure/`.

## 3. GREEN — the smallest thing that passes

**Minimum is literal.** If a hard-coded return makes the test pass and nothing else
breaks, that is a legitimate green: it proves the test is not yet constraining enough,
and the next cycle forces generalisation.

Do not add error handling, logging or configuration no test demands. Do not implement
the edge case you can already see coming — that is the next RED.

If the behaviour seems to need a model in order to be tested, that is the signal to
move the decision into `domain/` and pass the model's output in as data. Say so out
loud rather than writing a test around a fake's scripted reply.

Raise `ValueError` for anything a caller could fix — a bad value, a missing
key. Do not call `sys.exit` outside `cli/`: a library that kills the
interpreter cannot be used from a test or a notebook.

## 4. Green, then refactor

```bash
uv run pytest tests/unit/test_<x>.py -q   # the one test
uv run pytest -q                           # everything
```

Both must pass before you touch the shape of the code. Then tidy — names,
duplication, the comment explaining *why* — and re-run.

## 5. Comment the reasoning, not the mechanism

The convention in this repo is that comments explain why a thing is the way it
is, especially when it is surprising:

```python
# Zero is excluded on purpose: "score no traces" is a stop, not a sample rate.
# MLflow rejects it too, but inside start(), which means the first judge in the
# loop raises while earlier ones are already running.
```

If a rule exists because something broke, say so. Half the comments in
`domain/judges.py` are there because that exact bug reached a server once.

## 6. Full validation

```bash
uv run pytest              # 135+ tests, ~6s, no services needed
uv run ruff check .
uv run ruff format .
```

`tests/architecture/` runs here too, which checks both the import contracts and
that every spec rule still names a test that exists.

## CHALLENGE — name the next edge case

Propose the single most valuable next case, and say why it matters. Draw it from the
spec's counter-examples first, then from boundaries the code now visibly ignores:
empty input, exactly-at-threshold, zero, unicode, a duplicate id, a null.

If you believe the rule is fully covered, say that instead, and name which spec rule
`/accept` should take next.

## STOP — report and wait

1. The test added, and the exact red message it produced.
2. The production code written, in a sentence or two.
3. What the refactor changed, or that none was needed.
4. The proposed next edge case.
5. Full-suite status.

Then wait. Do not begin the next cycle.

**Escape hatch:** only when the user passes `--to-green <test>`, loop RED/GREEN/REFACTOR
without stopping until that test passes. Still one test at a time, still minimum code,
still the full suite green between cycles, and report every cycle in the summary so the
sequence stays reviewable.

## When the implementation disagrees with the spec

Stop. Do not quietly change either one.

The spec is authoritative, but a spec written from a wrong assumption is worth
knowing about. Say which one you think is wrong and why, and let the user
decide. The disagreement is the finding.

Hand over to `/verify` when the rule is complete.
