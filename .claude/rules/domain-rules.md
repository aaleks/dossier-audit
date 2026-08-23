---
paths:
  - "src/dossier/domain/**"
---

You are editing the domain layer — pure decisions. This is the most important
boundary in the project, and the reason the suite runs offline in seconds.

- **Imports the standard library and `pydantic`, and nothing else.** No `httpx`,
  no `yaml`, no `typer`, no `mlflow`, no `sqlite3`, no `pathlib`. A PreToolUse hook
  blocks the write and `tests/architecture/test_layer_contracts.py` fails the build;
  both are telling you the same thing.
- **Never read `os.environ` here, and never open a file.** A function takes what it
  needs as an argument: `window_start(last_sync_at, overlap)`, not
  `window_start(source_id)` reaching for a ledger. That is what lets a test hand it a
  dict instead of building a workspace, and it is why the unit tests need no fixtures.
- **Deterministic, and mechanically so.** No `datetime.now()`, no `random`, no
  `uuid4()`, no `hash()`, no reliance on dict or set iteration order, no absolute
  paths, no locale- or timezone-dependent formatting. R0.4 and R5.6 are claims that
  cache keys are byte-identical across machines; a single clock read here makes them
  untestable. Take a clock or an id generator as a parameter if you need one.
- **Sort before you hash.** Any collection entering a cache key is ordered
  canonically first. Two inputs supplied in a different order are the same inputs
  (R5.6 example 4), and relying on the order they happened to arrive in is the exact
  bug that makes a cache work on one machine and miss on another.
- This is where key composition, reference resolution, the normalisation projection,
  span checking, scoring, model-id validation and eligibility checks belong — not in
  `infrastructure/`, and not inline at the call site.
- Prefer small pure functions and frozen dataclasses over stateful classes.
- Raise `ValueError` for anything a caller could fix. Never `sys.exit` — that belongs
  to `cli/` alone.
- If a function keeps accreting cases, that is design pressure: extract a named value
  object with its own test rather than growing a branch tree.

Every rule here should be provable by a unit test with exact assertions. If you cannot
see how to assert it, it may not belong in this layer.
