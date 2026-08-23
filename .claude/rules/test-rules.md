---
paths:
  - "tests/**"
---

You are editing tests. Tests are executable specifications.

- **No real model call. Ever.** Use the `fake_llm` fixture (`FakeListChatModel`).
  A test that hits a provider is slow, costs money, and answers differently every run.
  The one exception is `tests/integration/test_judges_live.py`, which is marked `live`,
  excluded from the default suite, and exists because the rule it proves is
  `evaluated` and cannot be checked any other way.
- **Never assert LLM prose.** `assert answer == "Paris is the capital"` is a future
  flake, not a test. Assert structure: a boolean verdict, a schema, an exit code, a
  printed line, which backend attached. Fuzzy quality claims are `evaluated` rules and
  belong to a judge with a threshold.
- Prove each rule at the lowest tier that can prove it: `tests/unit/` for a `domain/`
  decision, `tests/acceptance/` for what a CLI user observes. Do not assert the same
  thing in both.
- Name the test after the business rule —
  `test_zero_override_is_honoured_not_treated_as_absent`, never `test_temperature_2`.
  Put the plain-language case in the docstring: `"""The one where --provider beats
  DEFAULT_PROVIDER."""`
- Use the `clean_env` fixture when a test reads configuration, so it does not pass or
  fail depending on the developer's real `.env`.
- **Every new test file must be named by a spec rule's `Proved by:` line**, or
  `tests/architecture/test_spec_coverage.py` fails. That is deliberate: an unclaimed
  test is behaviour nobody agreed to.
- **Never weaken or delete an existing test to make code pass.** Fix the code. If the
  test is genuinely wrong, the spec rule behind it is wrong too — say so and stop.
