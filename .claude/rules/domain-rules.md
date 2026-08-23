---
paths:
  - "src/playground/domain/**"
---

You are editing the domain layer — pure decisions. This is the most important
boundary in the project, and the reason the suite runs in six seconds.

- **No `langchain`, `mlflow`, `langfuse`, `litellm` or `dotenv` imports.** No HTTP,
  no file IO, no network. A PreToolUse hook blocks the write and import-linter fails
  the build; both are telling you the same thing.
- **Never read `os.environ` here.** A function takes the environment as an argument:
  `resolve_model(env, provider, override)`. That is what lets a test hand it a dict
  instead of monkeypatching the process, and it is why the unit tests need no fixtures.
- Deterministic: same input, same output. No `random`, no `datetime.now()`, no
  `uuid4()`. Take a clock or an id generator as a parameter if you ever need one.
- This is where precedence rules, validation, eligibility checks, drift detection and
  masking belong — not in `infrastructure/`, and not inline at the call site.
- Prefer small pure functions and frozen dataclasses over stateful classes.
- Raise `ValueError` for anything a caller could fix. Never `sys.exit` — that belongs
  to `cli/` alone.
- If a function keeps accreting cases, that is design pressure: extract a named value
  object with its own test rather than growing a branch tree.

Every rule here should be provable by a unit test with exact assertions. If you cannot
see how to assert it, it may not belong in this layer.
