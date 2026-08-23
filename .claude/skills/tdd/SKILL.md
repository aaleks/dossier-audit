---
name: tdd
model: claude-sonnet-5
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
description: Run ONE inner-loop cycle - red, green, refactor, challenge, stop. Drives a single failing unit test to green with the minimum code, then proposes the next edge case. Use after /accept has opened the outer loop. One cycle per invocation.
argument-hint: "<test or behaviour to drive> [--to-green <test>]"
---

Run ONE inner cycle for: $ARGUMENTS — one failing test driven to green, refactored,
then STOP.

**One cycle = one test.** A single new test function, or one new case added to an
existing `parametrize` list. It is *not* "drive until everything passes" — that is the
outer loop, and it closes on its own when enough inner cycles have landed. The edge
case you propose in CHALLENGE becomes the next RED in a **new** invocation.

The only exception is run-to-green mode, which the user must request explicitly with
`--to-green`. Never assume it.

## Where you are

```
OUTER   /accept ── acceptance test, red ─────────────────────▶ green, slice done
                      │                                 ▲
INNER                 └─ /tdd ─ /tdd ─ >>you<< ─ /tdd ──┘
```

The outer acceptance test is **expected to stay red** while you work. It is excluded
from the default suite by the `outer_loop` marker, so "the suite is green" and "the
slice is unfinished" are both true at once, and neither is confusing.

At the end of every cycle, check whether the outer loop has closed:

```bash
uv run pytest -m outer_loop -q
```

When it finally passes, say so loudly — that is the slice landing, and step 7 below
says what to do about it.

## The loop

```
RED  →  GREEN  →  REFACTOR  →  CHALLENGE  →  STOP
```

Do not collapse green and refactor into one step. Getting it working and getting it
right are different problems, and solving both at once is how you end up with neither.

## 1. Confirm red, and why

```bash
uv run pytest tests/unit/test_R002_4__<...>.py -q
```

If it is not red, stop — there is nothing to do here, and something upstream is wrong.
Go back to `/accept`.

## 2. Choose the layer

| The rule is about | Layer | Constraint |
|---|---|---|
| A decision: what changed, which key, which input, is it valid | `domain/` | Imports stdlib and `pydantic` only. No clock, no IO, no `os.environ`. |
| Loading `sources.yaml`, `pipeline.yaml`, credentials | `config/` | The only package that reads the environment. |
| A use case: sync, convert, run, plan, eval | `application/` | Takes the connector, store and model client as arguments. Never constructs one. |
| A network call | `infrastructure/connectors/` | The **only** package left of the hash boundary. |
| A converter, the store, the ledger, tracking | `infrastructure/` | Wiring, not judgement. SDK imports inside functions. |
| Flags, output, exit codes | `cli/` | The only place `sys.exit` is allowed. |

**Default to `domain/`.** If a rule can be expressed as a pure decision, put it there —
that is what makes it testable in milliseconds without a workspace, and it is the only
layer mutation testing can afford to run on.

Two PreToolUse hooks fire at write time here. If one blocks you, you picked the wrong
layer: the decision goes in `domain/`, the call that acts on it goes in
`infrastructure/`, and the network call goes in `connectors/` and nowhere else.

## 3. GREEN — the smallest thing that passes

**Minimum is literal.** If a hard-coded return makes the test pass and nothing else
breaks, that is a legitimate green: it proves the test is not yet constraining enough,
and the next cycle forces generalisation.

Do not add error handling, logging or configuration no test demands. Do not implement
the edge case you can already see coming — that is the next RED.

If the behaviour seems to need a model in order to be tested, that is the signal to
move the decision into `domain/` and pass the model's output in as data. Say so out
loud rather than writing a test around a fake's scripted reply.

Two things this project will not forgive, so watch for them while writing:

- **Sort before hashing.** Any collection entering a cache key is ordered canonically
  first. R5.6 says keys are byte-identical across machines; a set iteration is how that
  quietly stops being true.
- **Take the clock as an argument.** `datetime.now()` in `domain/` is blocked by a
  hook, and for a reason: R0.4 and R4.8 are claims about byte-identical output.

Raise `ValueError` for anything a caller could fix — a bad value, a missing key. Do not
call `sys.exit` outside `cli/`: a library that kills the interpreter cannot be used from
a test or a notebook.

## 4. Green, then refactor

```bash
uv run pytest tests/unit/test_R002_4__<...>.py -q   # the one test
uv run pytest -q                                     # the default suite
```

Both must pass before you touch the shape of the code. Then tidy — names, duplication,
the comment explaining *why* — and re-run.

## 5. Comment the reasoning, not the mechanism

The convention here is that comments explain why a thing is the way it is, especially
when it is surprising:

```python
# The window starts an overlap BEFORE the watermark, not at it. Clock skew between
# dossier and the source, plus source-side indexing lag, otherwise drops items
# silently -- and a silently missing document is indistinguishable from one that
# genuinely did not change (R2.4).
```

If a rule exists because something broke, say so. A comment naming the rule id is worth
more than one describing the code, because the rule is what a reader can go and check.

## 6. Full validation

```bash
uv run pytest              # the default suite: offline, seconds, zero cost
uv run ruff check .
uv run ruff format .
```

`tests/architecture/` runs there too, which checks the layer contracts, the hash
boundary, and that every spec rule still names a test that exists.

## 7. Did the outer loop close?

```bash
uv run pytest -m outer_loop -q
```

If it now passes, the slice has landed. Then, and only then:

1. Remove `pytestmark = pytest.mark.outer_loop` from the acceptance test, so it joins
   the default suite permanently.
2. Set the rule's `**Status:**` in the spec from `IN PROGRESS` to `MET`.
3. Update the spec's header status if every rule in it is now `MET`.
4. Run `uv run pytest tests/architecture -q` — it verifies both halves agree.

Do not do any of that early. A marker removed while the test is still red turns the
default suite red for everyone.

## CHALLENGE — name the next edge case

Propose the single most valuable next case, and say why it matters. Draw it from the
spec's counter-examples first — in this project the counter-example row is usually the
boundary and usually the untested one — then from boundaries the code now visibly
ignores: empty input, exactly-at-threshold, zero, a missing version marker, a duplicate
key, a null.

If you believe the rule is fully covered, say that instead, and name which spec rule
`/accept` should take next.

## STOP — report and wait

1. The test added, and the exact red message it produced.
2. The production code written, in a sentence or two.
3. What the refactor changed, or that none was needed.
4. Outer loop status: still red (and on which assertion), or closed.
5. The proposed next edge case.
6. Default suite status.

Then wait. Do not begin the next cycle.

**Escape hatch:** only when the user passes `--to-green <test>`, loop
RED/GREEN/REFACTOR without stopping until that test passes. Still one test at a time,
still minimum code, still the default suite green between cycles, and report every
cycle in the summary so the sequence stays reviewable.

## When the implementation disagrees with the spec

Stop. Do not quietly change either one.

The spec is authoritative, but a spec written from a wrong assumption is worth knowing
about. Say which one you think is wrong and why, and let the user decide. The
disagreement is the finding.

Hand over to `/verify` when the slice is complete.
