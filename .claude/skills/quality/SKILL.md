---
name: quality
model: claude-opus-5
allowed-tools: Read, Glob, Grep, Bash, Write, Agent
description: Run the spec-compliance, architecture-guardian and mutation-analyst agents and consolidate their findings into quality-report.md, grouped by severity. Use before a PR, or after a slice lands. Read-only apart from the report it writes.
argument-hint: "[--mutation] [--determinism]"
---

# /quality — one report from the auditors

Fan out to the agents in `.claude/agents/`, then reconcile three different vocabularies
into one severity ranking and leave a file behind.

**This is not `/verify`.** `/verify` is a reading task done in the main context: it asks
whether a named test actually *proves* its rule, which needs the spec and the test held
in one head. `/quality` is the opposite shape — independent agents, fresh context each,
a persisted artifact. Run `/verify` when you doubt a specific rule. Run `/quality`
before a PR, when you want the whole surface checked and a record of what was found.

Report findings. Fix nothing. That is the agents' rule and it is this skill's rule too.

## Gate 0 — the mechanical checks, once

```bash
uv run pytest tests/architecture -q
```

Both `spec-compliance` and `architecture-guardian` open by running this exact command
and stopping if it fails. Running it here first means a red suite costs one command
instead of two agents that each rediscover it.

If it fails, **stop and report**. But say *which* red this is, because they mean
different things:

| What failed | What it means | Severity |
|---|---|---|
| `test_R000_1__no_network_right_of_the_hash_boundary` | Reproducibility is broken. A replay can now return a different answer. | **Critical**, above everything |
| An import contract or a purity check | A layer boundary was crossed | **Critical** |
| A test file no rule claims | Behaviour was added and the spec was never updated | **Critical** |
| A rule that is `MET` or `IN PROGRESS` names a test that does not exist | The status is lying | **Critical** |
| More than one rule `IN PROGRESS` | Two open slices; neither will finish | **Major** |

And the one that is **not** a defect: a rule marked `NOT MET` whose test does not
exist. That is a rule agreed and not yet built — the ordinary state of most of this
repository. The checker does not fail on it and neither should you. Reporting it as a
defect trains people to ignore the check, which is the one outcome that makes it
worthless.

## Steps 1 and 2 — spec compliance and architecture, in parallel

Independent of each other, so issue both `Agent` calls **in one message**.

**Step 1 — `spec-compliance`.** Audit `specs/` against `src/dossier/` and `tests/`,
both directions. Ask for a verdict per rule as `COVERED` / `PARTIAL` / `MISSING`, each
with the file and line that justifies it, and ask it to weight the reproducibility rules
(R0.1–R0.6, R4.7, R5.6) above the rest.

**Step 2 — `architecture-guardian`.** Audit the whole of `src/dossier/`. Ask for
`VIOLATION` / `WARNING` / `NOTE`, and specifically for what the `ast` checks cannot see:
a decision sitting in `infrastructure/` that belongs in `domain/`, a connector that
normalises a payload before returning it, a client constructed inline, a `sys.exit`
outside `cli/`.

## Step 3 — mutation analysis, opt-in

The gate here is **cost, not availability**. `mutation.toml` is committed, so cosmic-ray
is always configured; what varies is whether you want to spend several minutes on the
`domain/` mutants.

- `--mutation` passed → run the `mutation-analyst` agent. It owns the
  `cosmic-ray init` / `exec` / `cr-report` sequence; do not run those yourself.
- not passed → skip, and record it in the report as skipped with the command to run.
  Silence would read as "no survivors".
- `mutation.toml` absent → note that mutation testing is not configured and skip. It
  should never be absent; if it is, that is itself a finding.

Scope is `src/dossier/domain` only, by design — the reasoning is in `mutation.toml`. A
quality report claiming to have mutation-tested the whole codebase would be false.

## Step 4 — determinism, opt-in

`--determinism` runs the `determinism-auditor` agent. In most projects that is a testing
concern; here it is also a product requirement, because R0.4 and R5.6 claim cache keys
are byte-identical across machines. The agent audits both halves — the suite, and key
composition itself. Cheap. Worth passing whenever the diff touched `tests/` **or**
`domain/keys.py`.

## Severity mapping

Three agents, three vocabularies. Reconcile them with this table rather than improvising
per run, or the same finding gets a different severity each time and the report stops
being comparable to the last one.

| Source | Its label | Report severity | Why |
|---|---|---|---|
| gate 0 | hash boundary failed | **Critical** | Reproducibility is gone, and silently |
| gate 0 | import contract or purity failed | **Critical** | The build is red |
| gate 0 | test file unclaimed by a rule | **Critical** | Behaviour exists that nothing describes |
| spec-compliance | `MISSING` | **Critical** | A rule states an invariant nothing checks |
| architecture-guardian | `VIOLATION` | **Critical** | A boundary is crossed |
| determinism-auditor | a key leak, or a real model call | **Critical** | Presents as flaky infrastructure for weeks before anyone finds it |
| spec-compliance | `PARTIAL` | **Major** | The test proves less than the rule claims — the gap `/verify` step 2 exists for |
| architecture-guardian | `WARNING` | **Major** | Misplaced logic; a decision outside `domain/` |
| determinism-auditor | a prose assertion, a missing count assertion | **Major** | A flake, or an under-proved rule |
| mutation-analyst | survivor in a function a spec rule names | **Major** | An assertion that would not notice being wrong, on a rule someone relies on |
| mutation-analyst | survivor elsewhere in `domain/` | **Minor** | Same defect, no rule leaning on it yet |
| architecture-guardian | `NOTE` | **Minor** | |
| spec-compliance | `COVERED` | **Informational** | Count these. Do not list them — a report that lists all 71 buries the four that failed |

## Output

Write `quality-report.md` at the repo root. Overwrite it; it is generated, and a stale
one is worse than none. It is gitignored, so it is a working artifact rather than a
committed one.

```markdown
# Quality report

> Generated by /quality on <branch> at <commit sha>
> Steps run: gate 0, spec-compliance, architecture-guardian
> Steps skipped: mutation-analyst (pass --mutation), determinism-auditor

## Verdict

<One sentence. "Clean" only if every step ran and returned nothing.>

## Critical

| # | Finding | Where | Source |
|---|---------|-------|--------|

## Major
## Minor
## Informational

## Coverage summary

| Spec | Rules | Covered | Partial | Missing | Not met |
|------|-------|---------|---------|---------|---------|

## Outer loop

<Which rule is IN PROGRESS, and whether its acceptance test is still red. "None
open" is a valid answer.>

## Not checked

<Every step skipped, and the command that would run it. This section is
mandatory and never empty unless all four steps ran.>
```

## Rules for this skill

1. **Never fix.** Every agent here is read-only and so is this. A finding acted on in
   the same pass is a finding nobody reviewed.
2. **Never invent a severity for a finding an agent did not make.** If you notice
   something yourself, put it under Informational and label it as yours.
3. **An agent that returns nothing returns nothing.** Write "returned no findings",
   never "clean" — those differ, and the second is a claim about the code that a silent
   agent did not make.
4. **A skipped step goes in "Not checked".** What is not met gets recorded, not omitted.
5. **A `NOT MET` rule is not a finding.** It is the spec being ahead of the code, on
   purpose.
6. **The verdict must be readable in one line.** If someone has to read the tables to
   know whether to open the PR, the verdict failed.
