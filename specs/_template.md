# NNN — <title>

**Status:** Proposed
**Rules:** RN.1 – RN.x

## Purpose

One paragraph. What this spec makes true, and what goes wrong without it.

## <Design sections>

Tables, examples and diagrams. This half is prose — it explains the mechanism so
a reader understands the rules below. Nothing here is checked mechanically.

## Must hold

Every rule below is an invariant: a claim that can be false. Each one is parsed by
`tests/architecture/test_spec_coverage.py`, so the shape matters.

### RN.1 — <short title, stating the claim>

<The rule, in one or two sentences. Say what is true, not what a function does.
"The provider is chosen by override, then .env, then the default" — not "the
provider is resolved". The first can be false; the second cannot.>

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.<module>.<callable>`)
- **Proved by:** `tests/unit/test_RNNN_1__<description>.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | <real values, from `specs/_fixtures.md`> | <the observable outcome> |
| 2 | <a boundary> | <outcome> |
| 3 | *counter-example* — <where the rule deliberately does not apply> | <what happens instead> |

### RN.2 — <an evaluated rule looks like this>

<A judgement about generated text. Everything else should have been split out
first — see `.claude/skills/discover/references/splitting-rules.md`.>

- **Kind:** evaluated
- **Layer:** application (`dossier.application.eval`)
- **Proved by:** `tests/evals/test_RNNN_2__<description>.py`
- **Threshold:** OPEN — needs ~20 labelled cases before a number means anything
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | <a real case> | <the scored outcome> |
| 2 | *counter-example* — <where the judge must not fire> | <outcome> |

## Field reference

| Field | Values | Meaning |
|---|---|---|
| **Kind** | `deterministic` | Same input, same output. Provable with `==`. |
| | `evaluated` | A judgement about generated text. Needs a threshold. |
| **Layer** | `domain` / `application` / `infrastructure` / `config` / `cli` | Where the decision lives. See `docs/architecture.md`. |
| **Proved by** | a `tests/...` path in backticks | The test file. It may not exist yet; name it anyway. |
| **Threshold** | a number and who agreed it, or `OPEN` | `evaluated` rules only. Never invent one. |
| **Status** | `NOT MET` | Written, not built. No test needs to exist. |
| | `IN PROGRESS` | The open outer loop. Its test exists and is red. At most one rule repo-wide. |
| | `MET` | The named test exists and passes in the default suite. |
