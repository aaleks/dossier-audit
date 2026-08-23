---
paths:
  - "tests/**"
---

You are editing tests. Tests are executable specifications.

- **No real model call. Ever.** Use the `fake_model` fixture (`FakeModelClient`), or
  `no_model` for the rules that permit zero calls. A test that hits a provider is
  slow, costs money, and answers differently every run. The only exception is
  `tests/evals/`, marked `live`, excluded from the default suite, and existing because
  the rules there are `evaluated` and cannot be checked any other way.
- **No network, and the suite enforces it.** The autouse `no_network` fixture blocks
  socket creation for every test that is not marked `live`. If a test fails with
  `NetworkAccessDuringTest`, do not work around it — that is R0.1 catching something.
- **Assert counts, not just values.** R2.5, R4.6, R5.5 and R5.7 are claims about how
  many fetches, writes or model calls happened. `fake_model.call_count == 0` is the
  assertion; a canned response proves nothing about them.
- **Never assert model prose.** `assert "cable fault" in answer` is a future flake,
  not a test. Assert structure: a boolean verdict, a schema, an exit code, a printed
  line, a hash, a call count. Fuzzy quality claims are `evaluated` rules and belong to
  a judge with a threshold.
- Prove each rule at the lowest tier that can prove it: `tests/unit/` for a `domain/`
  decision, `tests/acceptance/` for what a CLI user observes, `tests/integration/`
  for wiring and config loading. Do not assert the same thing in two tiers.
- **File names carry the rule id**: `test_R002_4__watermark_overlap_refetches_boundary_items.py`.
  The class docstring quotes the rule with its id; the test *function* is named after
  the business case, never the mechanism —
  `test_a_changed_document_is_the_only_one_refetched`, not `test_sync_2`. Put the
  plain-language case in the docstring: `"""The one where nothing changed."""`
- **Every test file must be named by a spec rule's `Proved by:` line**, or
  `tests/architecture/test_spec_coverage.py` fails. That is deliberate: an unclaimed
  test is behaviour nobody agreed to.
- **Transcribe the example table.** Each row of a rule's table is a test case,
  including the `*counter-example*` row — that row is usually the only thing standing
  between a real test and one that would pass against a stub returning zero.
- Use the `workspace` fixture rather than writing into `tests/fixtures/` directly. A
  sync writes a ledger and a snapshot store, and a test that leaves those behind
  changes the result of the next one.
- **Never weaken or delete an existing test to make code pass.** Fix the code. If the
  test is genuinely wrong, the spec rule behind it is wrong too — say so and stop.
- **Never edit `tests/evals/golden/` or `gold/`.** A hook blocks it. Editing expected
  answers until a score passes is how a threshold dies; propose the cases and let a
  human write the file.
