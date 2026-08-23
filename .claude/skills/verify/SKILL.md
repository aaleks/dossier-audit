---
name: verify
model: claude-opus-5
allowed-tools: Read, Glob, Grep, Bash
description: Audit that specs and code still agree, in both directions - spec2code and code2spec - plus the code-quality dimensions a green suite hides. Use after /tdd, before a PR, or any time you want to know whether the repo has drifted. Read-only; reports findings and a verdict, modifies nothing.
argument-hint: "[spec id or path to focus on]"
---

# /verify — do the specs and the code still agree?

The automated half of this runs in the test suite. This skill is the half that
needs judgement: a test can check that a rule *names* a test, not that the test
*proves the rule*.

Report findings. Do not silently fix.

## 1. Run the mechanical checks first

```bash
uv run pytest tests/architecture -q
```

That covers four things, and each fails the build:

| Check | Catches |
|---|---|
| Import contracts | A layer boundary violated |
| Every rule names a test, or is marked NOT MET | A rule written, implementation forgotten |
| Every named test exists | A renamed or typo'd reference |
| Every test file is named by a spec | Behaviour added, spec never updated |

If any fail, that is the finding. Report and stop — no point auditing further
against a spec set that is already broken.

## 2. spec → code: does the named test actually prove the rule?

This is what the checker cannot do. For each rule:

1. Read the rule and its example table.
2. Open the named test.
3. Ask: **is every example row asserted?**

Common findings:

- The rule has four examples; the test asserts two. The other two are unproved.
- The counter-example has no test. Very common, and the counter-example is
  usually where the real boundary is.
- The test asserts an implementation detail — that a helper was called — rather
  than the observable outcome the rule states.
- The rule says "before any judge is touched" and the test only checks that an
  error is raised, not that nothing was started. The *timing* claim is unproved.

## 3. code → spec: is there behaviour no rule claims?

```bash
git diff main --stat -- src/
```

For each changed module, ask whether a rule covers what it now does. Look
especially for:

- A new branch or early return with no rule behind it.
- A changed default. Defaults are behaviour and belong in a spec.
- A new environment variable. If `.env.example` gained a line and no spec
  mentions it, that is drift.
- An error message a user will see. Messages are an interface.

## 4. Check the determinism tags are honest

For each `deterministic` rule: could this actually be asserted with `==`? If
the test hedges — `assert "sunny" in answer.lower()` — the rule is misclassified
and the test is flaky.

For each `evaluated` rule: is there a threshold, and did someone agree it? A
rule with `Threshold: OPEN` is honest. A rule with no threshold at all is not
a rule.

## 5. Check the unmet rules are still accurately unmet

Rules marked NOT MET are exempt from needing a test — which makes them a place
where things rot quietly, in both directions.

```bash
grep -rn "NOT MET\|Threshold:\*\* OPEN" docs/specs/
```

For each: has it since been implemented and nobody updated the status? Is it
still genuinely unmet, or has the requirement gone away?

## 6. When you doubt a test, measure it

The checks above prove a rule and a test are linked. They cannot tell you the test
would notice if the code were wrong. Mutation testing can:

```bash
uv run --with cosmic-ray cosmic-ray init mutation.toml mutation.sqlite
uv run --with cosmic-ray cosmic-ray exec mutation.toml mutation.sqlite   # ~5-10 min
uv run --with cosmic-ray cr-report mutation.sqlite
```

Hand the output to the `mutation-analyst` agent, which turns each survivor into a named
spec rule and a concrete killing assertion. Do not run it on every audit — reach for it
when a test looks thin, or after a refactor of `domain/`.

Read the score with the caveat in ADR 0006: 0 survivors means no survivor *among the
mutants the tool generates*, and chained boundary comparisons are partly outside its
operator set.

## 7. The dimensions a green suite hides

Import contracts catch imports. They do not catch **misplaced logic**, which is the
more common decay — and no linter will find it.

- **A decision that landed in the wrong layer.** An `if` on a threshold, a precedence
  choice, a validity check sitting in `infrastructure/` or inline in `cli/` instead of
  `domain/`. This is the single most common violation in an LLM codebase.
- **A model constructed inline** instead of taken as an argument. Always a blocker: it
  makes the use case untestable.
- **Prompt text inline** in a function body rather than a named constant in
  `application/`.
- **An assertion that holds for every possible implementation** is decoration, not a
  test.
- **A rule proved at too high a tier** — an acceptance test doing what a unit test
  could, which is slower and less precise.

## 8. Report

```markdown
## Mechanical checks
tests/architecture: <pass / N failed, which>

## spec -> code
- 004 R3: examples 2 and 4 are not asserted — the upper bound is untested
- 001 R1: counter-example (unknown provider) has no test

## code -> spec
- src/playground/domain/providers.py: new OLLAMA_KEEP_ALIVE variable, no rule

## Determinism
- 006 R2: tagged deterministic but the test uses a substring match

## Unmet rules
- 006 R3: still accurate, tool is still a stub
```

Give each finding a severity and a specific fix:

```
[BLOCKER | MAJOR | MINOR] <one-line title>
  Where:  path:line
  What:   what is wrong
  Why:    the concrete failure it causes
  Fix:    the specific change -- not "consider refactoring"
```

- **BLOCKER** — a failing mechanical check, a real model call in the default suite, an
  assertion on LLM prose, behaviour with no rule at all.
- **MAJOR** — a decision in the wrong layer, an unproved example, a weak assertion, an
  `evaluated` rule with no threshold.
- **MINOR** — naming, duplication, a stale comment.

Finish with one line: **SHIP** or **DO NOT SHIP**, and the single most important thing
to fix first.

If everything holds, say so plainly and say what you checked. "No drift across 6 specs,
33 rules and 4 mechanical checks" is a useful result. "Looks fine" is not — and do not
invent filler findings to look thorough.
