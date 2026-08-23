---
paths:
  - "docs/specs/**"
---

You are editing a specification. These are checked mechanically, so a sloppy edit
fails the build rather than merely reading badly.

- A rule is an **invariant**, not a description of a function. "The provider is chosen
  by override, then `.env`, then the built-in default" — not "the provider is resolved".
  The first can be false; the second cannot.
- Every rule needs a `**Kind:**` of `deterministic` or `evaluated`, and a
  `**Proved by:**` line naming a real `tests/...` path in backticks. Prose that gestures
  at being tested is rejected by `tests/architecture/test_spec_coverage.py`.
- The only exemption is a rule explicitly marked `NOT MET` or `Threshold: OPEN`.
  Silence is not an option.
- Examples use **real values**, never placeholders. They are the test cases.
- Example tables are `Given | Then` by default. Add a `When` column only when the
  action varies between rows of the same rule. A column reading `resolve` on every
  row is noise pretending to be structure -- put the verb in the rule sentence.
- Do not write Gherkin. The table is a spec format, not a discovery format; running a
  discovery session in Given/When/Then pushes toward mechanism over the business claim.
- Every rule needs at least one **counter-example** — a case where it deliberately does
  not apply. A rule with only positive examples is usually a truism or two rules.
- Keep rule ids (`R1`, `R2`, ...) stable. Tests reference them in docstrings; renumbering
  silently breaks that link.
- `evaluated` rules need a numeric threshold and who agreed it. Do not invent one — ask,
  or record it as OPEN.
