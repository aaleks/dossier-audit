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

## The method

This is **Example Mapping**, adapted. The original is a short conversation that breaks
a story into four kinds of card, and the four map onto what a `dossier` spec holds:

| Card | What it is | Here |
|---|---|---|
| **Story** (yellow) | What was asked for | The spec's `## Purpose` |
| **Rule** (blue) | One testable constraint | `### R2.4 — <the invariant>` |
| **Example** (green) | A concrete case that makes it unambiguous | A `Given \| Then` row |
| **Question** (red) | An unknown only the user can resolve | Asked now, or recorded `OPEN` |

Read the health of the map as you go. **A handful of rules, one or two examples each,
and few red cards is ready to build. A lot of red is not** — say so and stop rather
than writing a spec on top of unresolved questions. Many open questions is the single
clearest signal that a wrong assumption is about to get expensive.

Two places `dossier` departs from the original method, both deliberate:

- **Rules are invariants, not obligations.** The classic form is "Must…" / "Should…".
  Skip it. "Must handle a missing version marker" is an obligation and cannot be
  false; "a connector that cannot supply `remote_version` sets it to `None`" can.
- **An unresolved question can survive into the saved spec.** The original deletes
  the red cards before saving. Here, a question whose answer does not exist yet is
  recorded as `OPEN` with what would resolve it — see step 6.

## Workflow

1. **Check what already exists** (step 1 below).
2. **Draft the map** — rules, examples, counter-examples, open questions.
3. **Apply the quality checklist** before showing anything to anyone.
4. **Present the draft** in the session format below. Nothing is written yet.
5. **Resolve the answerable questions** with `AskUserQuestion`, one at a time.
6. **Fold the answers back in** and present the complete spec for review.
7. **Save only on approval.**

Steps 4 and 7 are not ceremony. This skill can write a numbered file and an index row;
a spec the user has not read should not appear in `specs/` with their name on the
commit.

## 1. Check what already exists

```bash
ls specs/
grep -ril "<keyword>" specs/
```

Read `specs/000-overview.md` first — the vocabulary is fixed there, and a rule that
invents a synonym for *snapshot*, *item* or *artifact* will read as describing a
different system.

If a spec covers the area, **add rules to it** rather than starting a new file. Two
specs describing one feature is how they start disagreeing. Adding a rule means
appending `R<spec>.<next>` — never renumbering, because test filenames encode the ids.

## 2. Split the request into rules

Ask, repeatedly: *what would I have to observe to say this is wrong?* Each answer is a
rule.

A rule is an **invariant**, not a description of a function.

| Bad | Good |
|---|---|
| "The sync window is computed" | "Sync asks for changes from `last_sync_at` minus an overlap, never from `last_sync_at`" |
| "Handles missing versions" | "A connector that cannot supply `remote_version` sets it to `None` rather than fabricating one" |
| "Validates the model config" | "A model value that is not fully version-pinned is rejected at load time" |

The good column states something that can be false. The bad column cannot. Note that
"Must handle missing versions" is still in the bad column — a modal verb does not make
a claim falsifiable.

**One rule, one constraint. If a sentence needs an "and" to join two independent
claims, it is two rules.** "An unchanged version is not fetched **and** an unchanged
payload is not stored" is R2.1 and R2.2, and keeping them joined would give you one
table where half the rows prove one half of the sentence.

Treat any rules the user already stated as a starting point. Refine, split, challenge.

If a rule you are writing contradicts one that already exists, **do not edit the old
one**. Its id is referenced by test filenames and by other rules. Add the new rule at
the end of the spec, and mark the old one `**Status:** SUPERSEDED by R<new>`. Tell the
user you did — a superseded rule is a change of mind about the product, and it should
be reviewed as one.

## 3. Classify each rule — the determinism boundary

The step that matters most, and the one specific to a project with a model in it.

| Kind | When | Gets |
|---|---|---|
| `deterministic` | Same input, same output | A test with exact assertions |
| `evaluated` | A judgement about generated text | An LLM judge with an agreed threshold |

Ask: **could I write `assert result == X`?** If yes, it is deterministic and almost
certainly belongs in `domain/`. If the honest answer is "well, roughly...", it is
evaluated.

**Never** write a rule that asserts an exact model output string. That is a flaky test
wearing a spec's clothes.

In `dossier` the expected ratio is lopsided, and deliberately so: 69 of the 71 rules
currently in `specs/` are deterministic. The two that are not are both judgements about
narrative text (R7.11, R7.12). If your draft is mostly `evaluated`, you have not
separated the decisions from the generation yet — read
`references/splitting-rules.md` and go back to step 2.

## 4. Ground each rule in concrete cases

Real values, **from `specs/_fixtures.md`**. Never "some input". `INC-4821`, `a3f9c1e2`,
`2026-08-06T09:00:00Z`, `anthropic:claude-sonnet-4-5-20250929`. If you need a value the
fixtures file does not have, propose adding it there rather than inventing a local one —
one vocabulary across eight specs is what lets an example row be transcribed straight
into a test.

**Two columns by default.** The action is almost always implied by the rule itself, and
a third column that reads `sync` on every row is noise pretending to be structure:

```markdown
| # | Given | Then |
|---|-------|------|
| 1 | `last_sync_at=2026-08-06T09:00:00Z`, default overlap | `since = 2026-08-05T09:00:00Z` |
| 2 | `watermark_overlap: 48h` | `since = 2026-08-04T09:00:00Z` |
```

Add a **When** column only when the action genuinely varies between rows of the *same*
rule. If every row would say the same verb, that verb belongs in the rule sentence.

### Every row must read back as "The one where…"

Write each row so the sentence forms without effort:

| The row | Reads as |
|---|---|
| `last_sync_at=2026-08-06T09:00:00Z`, default overlap → `since = 2026-08-05T09:00:00Z` | *The one where the overlap pulls the window back a day.* |
| *counter-example* — a source that has never synced → `since = None` | *The one where there is no watermark to subtract from.* |

That sentence is the deliverable, not a flourish. `/accept` puts it straight into the
test's docstring:

```python
def test_a_source_that_has_never_synced_asks_for_everything(self):
    """The one where there is no watermark to subtract from."""
```

A row you cannot phrase that way is a row nobody can name a test after — which
usually means it is not one case but two, or it is a restatement of the row above it.

This is a spec format, not a discovery ritual. Do not run the session in
Given/When/Then and do not write Gherkin: those are test shapes, and reaching for them
during discovery pushes you toward mechanism (`when window_start() is called`) instead
of the business claim.

Every rule also needs at least one **counter-example** — a case where it deliberately
does *not* apply, marked `*counter-example*` so the checker can find it:

```markdown
| 4 | *counter-example* — a source that has never synced | `since = None`; the overlap has nothing to subtract from |
```

A rule with only positive examples is often trivially true. The counter-example is
where the boundary is, and on a threshold rule **the counter-example is the off-by-one
test** — the one mutation testing is weakest at generating.

### Quality checklist — apply before showing anything

Run it as a checklist, not as a memory of having read one.

- [ ] **Normal case first.** Then boundaries, then genuinely different outcomes.
- [ ] Every row reads back as "The one where…".
- [ ] No rule joins two independent claims with an "and".
- [ ] No table row is restated as a prose bullet underneath. A bullet appears only if
      it adds a rule, a boundary or an outcome the table cannot hold.
- [ ] Where a boundary row is doing real work, one line says *why* it matters.
- [ ] Every rule has a `*counter-example*` row.
- [ ] No two rows differ only in a value while proving the same thing.
- [ ] Eight rules or fewer. More means the story is too big.
- [ ] Few enough open questions that building is not a guess.

The detail behind each:

- **Normal case first.** Then boundaries, then genuinely different outcomes.
- **No two examples that differ only in the value.** Two rows proving the same thing
  with `24h` and `48h` feel thorough and test one case. Keep them only if the second
  proves the value is actually read rather than hard-coded.
- **Say the count, not just the value.** In this project a great many rules are claims
  about *how many* fetches, writes or model calls happened. "0 fetched, 0 new
  snapshots" is a better Then than "nothing happens".
- **Merge duplicates across rules.** The same example under two rules usually means the
  two rules are one.
- **More than about eight rules means the story is too big.** Split it before any test.
- **A rule with no example is not understood yet.** Ask for one rather than inventing it.
- **An example needing three paragraphs of setup** means the design is wrong, or the
  rule crosses a layer boundary it should not.

## 5. Name the layer and the test

```markdown
- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.sync.window_start`)
- **Proved by:** `tests/unit/test_R002_4__watermark_overlap_refetches_boundary_items.py`
- **Status:** NOT MET
```

The layer comes from `docs/architecture.md`. Default to `domain` — if a rule can be
expressed as a pure decision it belongs there, and that is what makes it provable in
milliseconds without a workspace.

The test does not exist yet. Name it anyway, in the
`test_R<spec>_<rule>__<description>.py` form, and set `Status: NOT MET`. `NOT MET` is
the only exemption from the test having to exist, and it is explicit on purpose.

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
| 1 | What agreement threshold makes the root_cause judge reportable? | OPEN — needs ~20 human-scored cases, and the number is the domain expert's to agree |
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
Rule: sync asks from last_sync_at minus an overlap, never from last_sync_at
  Example:         The one where the overlap pulls the window back a day
                     last_sync_at 2026-08-06T09:00Z, overlap 24h  ->  since 2026-08-05T09:00Z
  Counter-example: The one where there is no watermark to subtract from
                     never synced  ->  since None, full listing
  Question:        should the overlap be per-source, or one global setting?
```

Say the count of each at the end of the draft — rules, examples, open questions. Four
rules with eleven questions is a different situation from four rules with one, and the
user should be able to see which they are looking at without counting.

## Output — only after approval

Copy `specs/_template.md` to `specs/NNN-<feature>.md` (or append rules to the spec
that already owns the area), add a row to the table in `specs/README.md`, and set the
spec status:

- `Proposed` — written, not built. This is what `/discover` produces.
- `Partially implemented` — some rules `MET`, others not.
- `Implemented` — every rule `MET`.

Keep rule ids stable. Tests reference them in filenames, and renumbering silently
breaks that link.

Then run `uv run pytest tests/architecture` and expect it to pass — every new rule is
`NOT MET`, which is exempt. What you must check by eye is that the shape checks pass:
Kind, Layer, Proved by, Status, two example rows and a counter-example on every rule.

Finish by telling the user: how many rules, the deterministic/evaluated split, how many
questions were resolved versus left OPEN, and which rule `/accept` should take first.
Do not start writing tests.
