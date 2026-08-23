---
paths:
  - "specs/**"
---

You are editing a specification. **The specs are the source of truth; the code is an
implementation of them.** These files are also parsed mechanically, so a sloppy edit
fails the build rather than merely reading badly.

- A rule is an **invariant**, not a description of a function. "Sync asks for changes
  from `last_sync_at` minus an overlap" — not "the sync window is computed". The
  first can be false; the second cannot.
- **One rule, one constraint.** If a sentence needs an "and" to join two independent
  claims, it is two rules. Split it before writing the table, or the examples end up
  proving one half and the counter-example the other.
- Rule ids are `R<spec>.<rule>` — `R2.4` is rule 4 of spec `002`. **Keep them
  stable.** Test filenames encode them (`test_R002_4__...py`), so renumbering
  silently breaks that link. Add at the end rather than renumbering.
- **A rule that stops being true is superseded, never deleted or rewritten in place.**
  Set `**Status:** SUPERSEDED by R2.10` and add the replacement at the end of the
  spec. The id survives, so every reference to it still resolves and the history of
  why the behaviour changed stays readable. Silently editing a rule's text to mean
  something new is the one edit that makes a spec untrustworthy: every test that
  cites it now claims to prove something nobody agreed. `test_spec_coverage.py`
  checks that the replacement exists and is itself in force.
- Every rule needs four fields, and `tests/architecture/test_spec_coverage.py`
  rejects the file without them:
  - `**Kind:**` — `deterministic` or `evaluated`
  - `**Layer:**` — where the decision lives, per `docs/architecture.md`
  - `**Proved by:**` — a real `tests/<tier>/...` path in backticks
  - `**Status:**` — `NOT MET`, `IN PROGRESS`, or `MET`
- `NOT MET` is the only exemption from the test having to exist. It is explicit on
  purpose: silence is not an option. `IN PROGRESS` means the open outer loop, and at
  most one rule repository-wide may carry it.
- Examples use **real values from `specs/_fixtures.md`**, never placeholders. They
  are the test cases — `INC-4821`, `a3f9c1e2`, `2026-08-06T09:00:00Z`. Do not invent
  a new incident key; add to `_fixtures.md` instead, so one vocabulary spans all
  eight specs.
- Write each row so it reads back as **"The one where …"**. That sentence is not
  decoration: `/accept` transcribes it into the test's docstring, so a row nobody can
  phrase that way is a row nobody can name a test after.
- Do not restate a table row as a prose bullet underneath. A bullet earns its place
  only when it adds a rule, a boundary or an outcome the table cannot hold. When a
  boundary row is doing real work, say in one line *why* it matters rather than
  repeating it.
- Example tables are `Given | Then` by default. Add a `When` column only when the
  action varies between rows of the same rule. A column reading `sync` on every row
  is noise pretending to be structure — put the verb in the rule sentence.
- Do not write Gherkin. The table is a spec format, not a discovery format; running a
  discovery session in Given/When/Then pushes toward mechanism over the business claim.
- Every rule needs at least one row marked **`*counter-example*`** — a case where it
  deliberately does not apply. A rule with only positive examples is usually a truism
  or two rules, and on a boundary rule the counter-example is the off-by-one test.
- `evaluated` rules need a `**Threshold:**` — a number *and who agreed it*, or `OPEN`
  with what would resolve it. Do not invent one. A number you made up becomes a test,
  becomes a gate, and is discovered to be arbitrary three features later.
- Cross-reference rather than restate. If a rule depends on another, name it — `(R2.7)`
  — instead of paraphrasing it. Two specs describing one behaviour is how they start
  disagreeing.
- When behaviour must change, **the spec changes first, in its own commit**, and the
  code follows in a second commit referencing it. A PR that changes a rule changes the
  matching test in the same PR.
