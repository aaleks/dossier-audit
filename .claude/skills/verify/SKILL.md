---
name: verify
model: claude-opus-5
allowed-tools: Read, Glob, Grep, Bash
description: Audit that specs and code still agree, in both directions - spec2code and code2spec - plus the code-quality dimensions a green suite hides. Use after /tdd, before a PR, or any time you want to know whether the repo has drifted. Read-only; reports findings and a verdict, modifies nothing.
argument-hint: "[spec id or rule id to focus on]"
---

# /verify — do the specs and the code still agree?

The automated half of this runs in the test suite. This skill is the half that needs
judgement: a test can check that a rule *names* a test, not that the test *proves the
rule*.

Report findings. Do not silently fix.

## 1. Run the mechanical checks first

```bash
uv run pytest tests/architecture -q
```

That covers several things, and each fails the build:

| Check | Catches |
|---|---|
| The hash boundary (R0.1) | A network import right of the line — reproducibility broken |
| Layer contracts | A boundary crossed, or `domain/` losing its purity |
| Rule shape | A rule with no Kind, Layer, Proved by, Status, examples or counter-example |
| Rule/test link | A rule that is not `NOT MET` naming a test that does not exist |
| Test claim | A test file no rule claims — behaviour nobody agreed to |
| Outer loop | More than one rule `IN PROGRESS`, or the marker on the wrong file |

If any fail, that is the finding. Report and stop — no point auditing further against a
spec set that is already broken.

Note the one thing that is **not** a failure: a rule marked `NOT MET` whose test does
not exist. That is a rule agreed and not yet built, which is the normal state of most
of this repository right now.

## 2. spec → code: does the named test actually prove the rule?

This is what the checker cannot do. For each rule:

1. Read the rule and its example table.
2. Open the named test.
3. Ask: **is every example row asserted?**

Common findings:

- The rule has four rows; the test asserts two.
- The `*counter-example*` row has no test. Very common, and it is where the real
  boundary is. In this project the counter-example is frequently the only row that
  would fail against a stub returning zero — R2.5 is the clearest case.
- The rule claims a **count** and the test asserts a value. "fetches zero payloads and
  writes zero snapshots" is not proved by checking the printed output alone.
- The test asserts an implementation detail — that a helper was called — rather than
  the observable outcome the rule states.
- The rule says "before any stage executes" (R4.1) and the test only checks that an
  error is raised, not that nothing ran. The *timing* claim is unproved.

## 3. code → spec: is there behaviour no rule claims?

```bash
git diff main --stat -- src/
```

For each changed module, ask whether a rule covers what it now does. Look especially
for:

- A new branch or early return with no rule behind it.
- A changed default. Defaults are behaviour and belong in a spec — the 24-hour overlap
  in R2.4 is a default that earned its own rule.
- A new environment variable. Under R1.8 credentials come from the environment, so a
  new variable is both new behaviour and a new place a secret could leak.
- An error message a user will see. Messages are an interface, and R3.1 makes the
  *content* of one an invariant.

## 4. Check the determinism tags are honest

For each `deterministic` rule: could this actually be asserted with `==`? If the test
hedges — `assert "48200" in output` — the rule is misclassified and the test is flaky.

For each `evaluated` rule: is there a threshold, and did **someone** agree it? A rule
with `Threshold: OPEN` and a note on what would resolve it is honest. A rule with a
number nobody can attribute is not.

Then the reverse, which is the more valuable pass: is anything tagged `evaluated` that
is really a decision? Re-read `.claude/skills/discover/references/splitting-rules.md`
and try to split it. Two evaluated rules out of seventy-one is the current ratio; a
third should have to justify itself.

## 5. Check the unmet rules are still accurately unmet

`NOT MET` rules are exempt from needing a test — which makes them a place where things
rot quietly, in both directions.

```bash
grep -rn "NOT MET\|SUPERSEDED\|Threshold:\*\* OPEN" specs/
```

For each `NOT MET`: has it since been implemented and nobody updated the status? Is it
still genuinely unmet, or has the requirement gone away?

For each `SUPERSEDED`: does the replacement actually cover what the old rule covered?
The checker proves the replacement *exists*; it cannot tell you the new rule left a
gap. A supersession that quietly drops a case is the most expensive thing in this
section, because the dropped case still has an id, still reads as agreed behaviour,
and no test fails.

Check the outer loop too. A rule sitting at `IN PROGRESS` across several sessions
means a slice that is not converging — say so, and say which inner cycle is missing.

## 6. When you doubt a test, measure it

The checks above prove a rule and a test are linked. They cannot tell you the test
would notice if the code were wrong. Mutation testing can:

```bash
uv run --with cosmic-ray cosmic-ray init mutation.toml mutation.sqlite
uv run --with cosmic-ray cosmic-ray exec mutation.toml mutation.sqlite   # several minutes
uv run --with cosmic-ray cr-report mutation.sqlite
```

Hand the output to the `mutation-analyst` agent, which turns each survivor into a named
spec rule and a concrete killing assertion. Do not run it on every audit — reach for it
when a test looks thin, or after a refactor of `domain/`.

Read the score with a caveat: 0 survivors means no survivor *among the mutants the tool
generates*, and chained boundary comparisons are partly outside its operator set. The
watermark window and the judge threshold are exactly that shape.

## 7. The dimensions a green suite hides

Contracts catch imports. They do not catch **misplaced logic**, which is the more common
decay — and no linter will find it.

- **A decision that landed in the wrong layer.** An `if` on a threshold, a precedence
  choice, a "has this changed" test sitting in `infrastructure/` or inline in `cli/`
  instead of `domain/`. This is the single most common violation.
- **A connector doing more than fetching.** Parsing, normalising or re-serialising a
  payload before returning it breaks R1.2 and silently changes every content hash.
- **A model client or store constructed inline** instead of taken as an argument.
  Always a blocker: it makes the use case untestable.
- **Prompt text inline** in a function body rather than a named constant.
- **An assertion that holds for every possible implementation** is decoration, not a
  test.
- **A rule proved at too high a tier** — an acceptance test doing what a unit test
  could, which is slower and less precise. The inverse also counts: a unit test
  asserting what a user observes proves less than the rule claims.

## 8. Report

```markdown
## Mechanical checks
tests/architecture: <pass / N failed, which>

## spec -> code
- R4.3: examples 2 and 3 are not asserted — the exact bound is untested
- R2.5: counter-example (one document changed) has no test

## code -> spec
- src/dossier/domain/sync.py: new grace-period branch, no rule

## Determinism
- R6.4: tagged deterministic but the test uses a substring match

## Unmet rules
- R7.11: still accurate, threshold still OPEN pending 20 labelled cases
```

Give each finding a severity and a specific fix:

```
[BLOCKER | MAJOR | MINOR] <one-line title>
  Where:  path:line
  What:   what is wrong
  Why:    the concrete failure it causes
  Fix:    the specific change -- not "consider refactoring"
```

- **BLOCKER** — a failing mechanical check, a network import right of the hash
  boundary, a real model call in the default suite, an assertion on model prose,
  behaviour with no rule at all.
- **MAJOR** — a decision in the wrong layer, an unproved example, a weak assertion, an
  `evaluated` rule with no threshold, a count claim proved by a value assertion.
- **MINOR** — naming, duplication, a stale comment.

Finish with one line: **SHIP** or **DO NOT SHIP**, and the single most important thing
to fix first.

If everything holds, say so plainly and say what you checked. "No drift across 8 specs,
71 rules and 6 mechanical checks" is a useful result. "Looks fine" is not — and do not
invent filler findings to look thorough.
