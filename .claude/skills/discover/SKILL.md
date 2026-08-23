---
name: discover
model: claude-opus-5
allowed-tools: Read, Glob, Grep, Write, AskUserQuestion
description: Turn a feature idea into a specification with testable rules, resolving the unknowns with the user interactively before anything is written to disk. Use at the START of a new capability or behaviour change, before any test exists. First step of the SDD loop; /accept comes next.
argument-hint: "<the feature request, in quotes>"
---

Run a discovery session for: $ARGUMENTS

A feature request is usually one unfalsifiable sentence. Your job is to surface the
rules hiding inside it, ground each in concrete cases, and resolve the ambiguity **with
the user** — not to write code, and not to guess at answers only they have.

`allowed-tools` deliberately excludes `Edit` and `Bash`: this skill cannot touch code.
If you find yourself wanting to implement, that is `/accept` and `/tdd`, later.

## Workflow

1. **Check what already exists** (step 1 below).
2. **Draft the map** — rules, examples, counter-examples, open questions.
3. **Apply the quality checklist** before showing anything to anyone.
4. **Present the draft** in the session format below. Nothing is written yet.
5. **Resolve the answerable questions** with `AskUserQuestion`, one at a time.
6. **Fold the answers back in** and present the complete spec for review.
7. **Save only on approval.**

Steps 4 and 7 are not ceremony. This skill can write a numbered file and an index row;
a spec the user has not read should not appear in `docs/specs/` with their name on the
commit.

## 1. Check what already exists

```bash
ls docs/specs/
grep -ril "<keyword>" docs/specs/
```

If a spec covers the area, **add rules to it** rather than starting a new file. Two
specs describing one feature is how they start disagreeing.

## 2. Split the request into rules

Ask, repeatedly: *what would I have to observe to say this is wrong?* Each answer is a
rule.

A rule is an **invariant**, not a description of a function.

| Bad | Good |
|---|---|
| "The provider is resolved" | "The provider is chosen by override, then `.env`, then the built-in default" |
| "Handles missing keys" | "Only a provider that needs a credential is checked for one" |
| "Validates the sample rate" | "The sample rate is validated before any judge is touched" |

The good column states something that can be false. The bad column cannot. Note that
"Must handle missing keys" is still in the bad column — a modal verb does not make a
claim falsifiable.

Treat any rules the user already stated as a starting point. Refine, split, challenge.

## 3. Classify each rule — the determinism boundary

The step that matters most, and the one specific to an LLM project.

| Kind | When | Gets |
|---|---|---|
| `deterministic` | Same input, same output | A test with exact assertions |
| `evaluated` | A judgement about generated text | An LLM judge with an agreed threshold |

Ask: **could I write `assert result == X`?** If yes, it is deterministic and almost
certainly belongs in `domain/`. If the honest answer is "well, roughly...", it is
evaluated.

**Never** write a rule that asserts an exact LLM string. That is a flaky test wearing a
spec's clothes.

Read `references/splitting-rules.md` for the four splitting angles and a worked example
— 7 of 9 judge rules in this repo came out deterministic that way. If everything you
have written is `evaluated`, you have not separated the decisions from the generation
yet; go back to step 2.

## 4. Ground each rule in concrete cases

Real values. Never "some input".

**Two columns by default.** The action is almost always implied by the rule itself, and
a third column that reads `resolve` on every row is noise pretending to be structure:

```markdown
| # | Given | Then |
|---|-------|------|
| 1 | `DEFAULT_PROVIDER=ollama`, `--provider openai` | `openai` |
| 2 | nothing set | `ollama` |
```

Add a **When** column only when the action genuinely varies between rows of the *same*
rule — the same input treated differently depending on what is done to it. If every row
would say the same verb, that verb belongs in the rule sentence, not in a column.

This is a spec format, not a discovery ritual. Do not run the session in Given/When/Then
and do not write Gherkin: those are test shapes, and reaching for them during discovery
pushes you toward mechanism (`when resolve() is called`) instead of the business claim.
Talk in plain sentences; the table is just how the agreed cases get recorded.

Every rule also needs at least one **counter-example** — a case where it deliberately
does *not* apply:

```markdown
| # | Given | Then |
|---|-------|------|
| 1 | provider `ollama`, no keys at all | rule does not apply; it runs locally |
```

A rule with only positive examples is often trivially true. The counter-example is
where the boundary is, and on a threshold rule **the counter-example is the off-by-one
test** — the one mutation testing is weakest at generating (ADR 0006).

### Quality checklist — apply before showing anything

- **Normal case first.** Then boundaries, then genuinely different outcomes.
- **No two examples that differ only in the value.** Two rows proving the same thing
  with `0.3` and `0.4` feel thorough and test one case. Cut one.
- **One compact table beats five repetitive bullets.** If a rule's inputs vary
  independently, a table with a column per input is clearer than prose.
- **Merge duplicates across rules.** The same example appearing under two rules usually
  means the two rules are one.
- **More than about eight rules means the story is too big.** Split it before any test.
- **A rule with no example is not understood yet.** Ask for one rather than inventing it.
- **An example needing three paragraphs of setup** means the design is wrong, or the
  rule crosses a layer boundary it should not.

## 5. Name the layer and the test

```markdown
- **Kind:** deterministic
- **Layer:** domain (`playground.domain.providers.resolve_provider`)
- **Proved by:** `tests/unit/test_providers.py::TestProviderSelection`
```

The test does not exist yet. Name it anyway — `/accept` writes it next, and
`tests/architecture/test_spec_coverage.py` fails until it does. That failure is the
forcing function that stops a spec describing a system nobody built.

## 6. Triage the unknowns — ask, or record

Two kinds of unknown, and the difference decides what you do:

| The answer... | Then |
|---|---|
| a human can give right now — a policy, a preference, a threshold they hold an opinion on | **Ask.** Use `AskUserQuestion`, one at a time, 3-4 concrete options drawn from the examples rather than open prose. Fold the answer in and delete the question. |
| does not exist yet — it needs data, a measurement, a run that has not happened | **Record it as OPEN**, and say what would resolve it. |

```markdown
## Open questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | What threshold makes summary_quality meaningful? | OPEN — needs ~20 eval cases before a number means anything |
```

An OPEN question is a legitimate output. **An OPEN question that a human could have
answered in one sentence is not** — that is a cop-out dressed as rigour, and it leaves
a hole someone fills with a guess later.

**Every `evaluated` rule needs a threshold, and you must ask for it.** A number you
invented becomes a test, becomes a gate, and is discovered to be arbitrary three
features later. Stop and ask rather than inventing any business rule.

## Session format

While the session is running, keep it plain. No file, no markdown scaffolding:

```
Rule: the provider is chosen by override, then .env, then the built-in default
  Example:         DEFAULT_PROVIDER=ollama with --provider openai  ->  openai
  Counter-example: --provider claude  ->  rejected, listing the valid names
  Question:        should an unknown provider fail, or warn and fall back?
```

## Output — only after approval

Copy `docs/specs/_template.md` to `docs/specs/NNN-<feature>.md`, fill it in, add a row
to the table in `docs/specs/README.md`, and set the status:

- `Proposed` — written, not built. This is what `/discover` produces.
- `Partially implemented` — some rules hold, others marked NOT MET.
- `Implemented` — all rules hold and are proved.

Keep rule ids (`R1`, `R2`, ...) stable — tests reference them in docstrings, and
renumbering silently breaks that link.

Then run `uv run pytest tests/architecture` and expect it to fail on the missing test.

Finish by telling the user: how many rules, the deterministic/evaluated split, how many
questions were resolved versus left OPEN, and which rule `/accept` should take first.
Do not start writing tests.
