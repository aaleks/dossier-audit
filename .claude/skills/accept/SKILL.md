---
name: accept
model: claude-sonnet-5
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
description: Write ONE failing test for the next deterministic spec rule, before any implementation exists. Use after /discover has agreed a spec, or when a rule has no test yet. Second step of the SDD loop; /tdd drives it to green.
argument-hint: "<rule id> <spec file>"
---

Write a failing test for: $ARGUMENTS

The rule is written. This turns it into a test that fails for the right reason,
**before** any implementation exists.

The failing test is the deliverable. Do not write production code in this skill.

## First: check the rule is deterministic

Look at its `**Kind:**` line in the spec.

- `deterministic` — continue.
- `evaluated` — **stop.** An evaluated rule cannot have an exact test; asserting on
  generated prose produces a flake that gets deleted in three weeks. Send the user to
  `/eval`, and offer to take the next deterministic rule instead.
- Missing — the spec is unfinished. Send the user back to `/discover`.

**One rule per invocation.** Do not write tests for rules the user did not name.

## Why the test comes first

A test written after the code tends to assert what the code happens to do. A
test written from the spec asserts what was agreed. When they differ, that
difference is the finding — and you only see it if the test came first.

Watching it fail matters just as much. A test that has never been red has never
been shown capable of failing.

## 1. Read the rule, not the code

Open the spec. Take one rule. Its example table is your test cases — the values
are concrete precisely so they can be transcribed.

Do not read the implementation first. If it exists, it will bias the test
toward what it does.

## 2. Pick the tier

| Tier | Use when | Directory |
|---|---|---|
| unit | The rule is a `domain/` decision | `tests/unit/` |
| acceptance | The rule is behaviour a CLI user observes | `tests/acceptance/` |
| integration | The rule is about wiring or config loading | `tests/integration/` |

Most deterministic rules are unit tests, because most rules here are decisions.
Reach for acceptance when the rule mentions what gets *printed*, an exit code,
or a flag.

## 3. Write it

One class per rule, named after the rule. One test per example row.

```python
class TestProviderSelection:
    """R1 — the provider is chosen by override, then .env, then the built-in."""

    def test_override_wins_over_env(self):
        """The one where --provider beats DEFAULT_PROVIDER."""
        assert resolve_provider({"DEFAULT_PROVIDER": "ollama"}, "openai") == "openai"
```

Naming:

- The test name states the **business rule**, not the mechanism:
  `test_zero_override_is_honoured_not_treated_as_absent`, never
  `test_temperature_2`.
- The class docstring quotes the rule with its `R` number.
- Include the counter-example. It is a test too.

Hard constraints:

- **No real model call.** Use the `fake_llm` fixture. A test that hits a
  provider is slow, costs money, and answers differently every run.
- **No exact LLM prose in an assertion.** If you want to, the rule is
  `evaluated` and belongs to a judge, not to pytest.
- Anything needing a running service gets `@pytest.mark.live`.
- **If you cannot inject a fake, the production code has a seam problem.** Say so and
  stop. Do not reach for `unittest.mock.patch` to paper over it — that hides the design
  problem and produces a test coupled to internals.

## 4. Run it and read the failure

```bash
uv run pytest tests/unit/test_<x>.py -q
```

It must fail. Then check **why**:

| Failure | Meaning |
|---|---|
| `AttributeError` / `ImportError` | Correct — nothing implements it yet. Proceed. |
| `AssertionError` with a plausible value | Something already does this. Stop and tell the user: the spec may be describing existing behaviour, which changes the job. |
| It passes | The test is wrong — it asserts something trivially true. Rewrite it. |

A test that passes before implementation is the failure mode to watch for.

## 5. Close the loop

Update the rule's `**Proved by:**` line to the real test path, then:

```bash
uv run pytest tests/architecture -q
```

That checks the reference resolves. It fails on a typo or a renamed class,
which is what makes the link real rather than decorative.

## Report

State, in this order:

1. The rule id and the file and test names written.
2. The **exact** failure message.
3. Why that failure is the correct red.

Then stop. `/tdd` drives it to green.
