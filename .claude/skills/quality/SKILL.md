---
name: quality
model: claude-opus-5
allowed-tools: Read, Glob, Grep, Bash, Write, Agent
description: Run the spec-compliance, architecture-guardian and mutation-analyst agents and consolidate their findings into quality-report.md, grouped by severity. Use before a PR, or after a slice lands. Read-only apart from the report it writes.
argument-hint: "[--mutation] [--determinism]"
---

# /quality — one report from the auditors

Fan out to the agents in `.claude/agents/`, then reconcile three different
vocabularies into one severity ranking and leave a file behind.

**This is not `/verify`.** `/verify` is a reading task done in the main context:
it asks whether a named test actually *proves* its rule, which needs the spec
and the test held in one head. `/quality` is the opposite shape — independent
agents, fresh context each, a persisted artifact. Run `/verify` when you doubt a
specific rule. Run `/quality` before a PR, when you want the whole surface
checked and a record of what was found.

Report findings. Fix nothing. That is the agents' rule and it is this skill's
rule too.

## Gate 0 — the mechanical checks, once

```bash
uv run pytest tests/architecture -q
```

Both `spec-compliance` and `architecture-guardian` open by running this exact
command and stopping if it fails. Running it here first means a red suite costs
one command instead of two agents that each rediscover it.

If it fails, **stop and report**. But say *which* red this is, because two of
them mean opposite things:

| What failed | What it means | Severity |
|---|---|---|
| A rule names a test that does not exist | Usually mid-loop: `/discover` landed a spec and `/accept` has not written its tests yet. Working as designed | **Expected** — name the rules, stop, do not escalate |
| A test file no spec claims | Behaviour was added and the spec was never updated | **Critical** |
| An import contract | A layer boundary was crossed | **Critical** |

The first row is the forcing function doing its job. Reporting it as a defect
trains people to ignore the check, which is the one outcome that makes it
worthless.

## Steps 1 and 2 — spec compliance and architecture, in parallel

Independent of each other, so issue both `Agent` calls **in one message**.

**Step 1 — `spec-compliance`.** Audit `docs/specs/` against `src/playground/`
and `tests/`, both directions. Ask for a verdict per rule as
`COVERED` / `PARTIAL` / `MISSING`, each with the file and line that justifies it.

**Step 2 — `architecture-guardian`.** Audit the whole of `src/playground/`. Ask
for `VIOLATION` / `WARNING` / `NOTE`, and specifically for what the contracts in
`pyproject.toml` cannot see: a decision sitting in `infrastructure/` that belongs
in `domain/`, or a `sys.exit` outside `cli/console.py`.

## Step 3 — mutation analysis, opt-in

Your instinct to gate this was right, but the gate here is **cost, not
availability**. `mutation.toml` is committed, so cosmic-ray is always configured;
what varies is whether you want to spend 5-10 minutes on ~330 mutants.

- `--mutation` passed → run the `mutation-analyst` agent. It owns the
  `cosmic-ray init` / `exec` / `cr-report` sequence; do not run those yourself.
- not passed → skip, and record it in the report as skipped with the command to
  run. Silence would read as "no survivors".
- `mutation.toml` absent → note that mutation testing is not configured and skip.
  It should never be absent; if it is, that is itself a finding.

Scope is `src/playground/domain` only, by design — see the reasoning in
`mutation.toml`. A quality report that claims to have mutation-tested the whole
codebase would be false.

## Step 4 — determinism, opt-in

`--determinism` runs the `determinism-auditor` agent: no test makes a real model
call, and no test asserts LLM prose. Not in the original three, but Rule 10 is
load-bearing in this repo and a violation is invisible until a test flakes in
CI. Cheap. Worth passing when the diff touched `tests/`.

## Severity mapping

Three agents, three vocabularies. Reconcile them with this table rather than
improvising per run, or the same finding gets a different severity each time and
the report stops being comparable to the last one.

| Source | Its label | Report severity | Why |
|---|---|---|---|
| gate 0 | import contract failed | **Critical** | The build is red |
| gate 0 | test file unclaimed by a spec | **Critical** | Behaviour exists that nothing describes |
| spec-compliance | `MISSING` | **Critical** | A rule states an invariant nothing checks |
| architecture-guardian | `VIOLATION` | **Critical** | A boundary is crossed |
| spec-compliance | `PARTIAL` | **Major** | The test proves less than the rule claims — the gap `/verify` step 2 exists for |
| architecture-guardian | `WARNING` | **Major** | Misplaced logic; a decision outside `domain/` |
| mutation-analyst | survivor in a function a spec rule names | **Major** | An assertion that would not notice being wrong, on a rule someone relies on |
| mutation-analyst | survivor elsewhere in `domain/` | **Minor** | Same defect, no rule leaning on it yet |
| architecture-guardian | `NOTE` | **Minor** | |
| determinism-auditor | any finding | **Critical** | A real model call or a prose assertion is a flake with a spec's clothes on |
| spec-compliance | `COVERED` | **Informational** | Count these. Do not list them — a report that lists every passing rule buries the four that failed |

## Output

Write `quality-report.md` at the repo root. Overwrite it; it is generated, and a
stale one is worse than none.

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

| Spec | Rules | Covered | Partial | Missing |
|------|-------|---------|---------|---------|

## Not checked

<Every step skipped, and the command that would run it. This section is
mandatory and never empty unless all four steps ran.>
```

## Rules for this skill

1. **Never fix.** Every agent here is read-only and so is this. A finding acted
   on in the same pass is a finding nobody reviewed.
2. **Never invent a severity for a finding an agent did not make.** If you notice
   something yourself, put it under Informational and label it as yours.
3. **An agent that returns nothing returns nothing.** Write "returned no
   findings", never "clean" — those differ, and the second is a claim about the
   code that a silent agent did not make.
4. **A skipped step goes in "Not checked".** Rule 9: what is not met gets
   recorded, not omitted.
5. **The verdict must be readable in one line.** If someone has to read the
   tables to know whether to open the PR, the verdict failed.
