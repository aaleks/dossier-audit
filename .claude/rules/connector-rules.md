---
paths:
  - "src/dossier/infrastructure/connectors/**"
---

You are editing a connector. This is one of the **four** packages left of the hash
boundary -- with `infrastructure/models`, `infrastructure/tracking` and
`infrastructure/index` -- and the only one that fetches a source (R0.17).

Everything downstream assumes that once a payload has been stored, it is frozen and
repeatable. That assumption is only as good as this package.

- **Return the payload byte-for-byte** (R1.2). Do not parse it, re-serialise it,
  strip a BOM, normalise line endings or reorder JSON keys. Normalisation happens
  later, in the ledger layer, for hashing only, and it never changes what is stored.
  A connector that "tidies up" a payload silently changes every content hash.
- **Never write to the source system** (R1.1). No create, update, delete or
  transition — including status-only side effects such as marking a page viewed.
  If an SDK method has a side effect, do not call it.
- **`remote_version` is `None` when the source has none** (R1.5). Do not substitute
  a fetch time, an mtime or an empty string. A fabricated version marker makes R2.1
  skip a fetch for an item that really did change, and nothing downstream can detect
  it.
- **Over-return rather than under-return** (R1.4). `list(since=t)` may include items
  that did not change; it may never omit one that did. When in doubt, widen the
  window — that is what the 24-hour overlap in R2.4 is for.
- **Credentials come from arguments, never from `os.environ` here** (R1.8).
  `dossier.config` reads the environment and passes the value in. A credential
  never reaches a log line, an exception message, a ledger row or a manifest. When
  you write an error message, name the URL and the status code, not the header.
- **Fail cleanly, item by item** (R1.9). An error on one item leaves the ledger
  untouched for that item. Never record an item you did not successfully store, and
  never let a partial fetch look like a complete one.
- **SDK imports go inside the function**, not at module scope. An unrelated command
  should not pay the import cost of a client it will never construct.
- **No decisions here.** "Skip when the version matches", "which items are in scope",
  "what counts as changed" are decisions and belong in `dossier.domain`. This package
  issues the request and hands back what it got. If you find yourself writing an `if`
  on a threshold or a precedence rule, you are in the wrong file.

Every connector must pass the same shared contract tests. If a new connector needs a
special case in the core package, the interface has failed (R1.7) — say so rather
than adding the special case.
