# Two proposals from exercise 15

These were written when the exercise found the behaviour, and neither has been
reviewed. They are one answer each, not the answer: write yours first. Behaviour
that is not in a spec does not get implemented (`CLAUDE.md`), so each one
proposes the spec change, and the code would follow it.

---

## 1. A step is not called for a document that has none of the kind it reads

**Found in task 4.** `extract` reads bare `documents`, which is
`documents@markdown` (R3.11). A Confluence page's PNGs convert to `page_images`
by default (R8.10), and a run's documents are every document that converted, in
whatever kind (R6.15). So `extract` is called for each PNG, and each call's
prompt has an empty string where the document should be. Two things follow:

- **A call is paid for about nothing.** A real model answers something, and a
  careful one answers nulls. Either way the answer is cached and served again.
- **Two such documents share one stage key.** The input of both is `""`, so the
  second is served the first's answer, and that answer names the first
  document's key. In task 4, `zstd-1.3.4.png.json` says it is about
  `zstd-1.3.3-vs-4.png`.

R6.13 already names this failure, in its own reasoning, for a document that an
earlier *step* produced nothing for: "asks a model about a document nobody
read, pays for the call, and caches an answer under a key whose input hash is
the hash of `""`". It does not cover a document that has no artifact of the kind
a step reads.

**Proposed.** Extend R6.13, or add a rule beside it: a `per_file` or `per_part`
step does not run for a document that has no artifact of the kind any of its
source inputs names. That means no model call, no artifact and no cache entry.
The run reports the document once, as skipped by that step, with the kind it
lacked, and not as failed. It did not fail. It was never the step's to read.

Rows it would need:

| Given | Then |
|---|---|
| `extract` reading `documents`, and `67637330/zstd-1.3.4.png` held as `page_images` only | no call for it; the step line counts it as skipped, not failed |
| *counter-example* — a `describe` step reading `documents@page_images` in the same pipeline | runs for both PNGs, and for neither page |
| *counter-example* — an `aggregate` step reading `documents` | unchanged: `_joined` already leaves out a document with no content |

**Considered and not proposed.** Wrapping the empty value as
`<document key="67637330/zstd-1.3.4.png"></document>` would give the two PNGs
different keys, so the second would no longer be served the first's answer. It
would keep the call, though, and it would ask a model about a document it was
never shown. That fixes the symptom and pays for the cause.

**What it does not settle.** Spec 008's open question 5, whether a source can
say which kind each media type converts to. That is a question about
conversion. This one is about which documents a step is asked about, and it
would be needed however open question 5 is answered.

---

## 2. A page is asked what it carries when what it carries may have changed

**Found in tasks 6 and 7.** `attachments(key)` is asked only for a page the
listing returns, and an incremental listing returns only pages modified inside
the window (R1.4, R1.15 row 2). Two rules assume otherwise. Both hold in their
unit tests, whose fake server returns the page whatever the window, and a third
case is covered by no rule at all:

- **R1.20 row 3.** A refused export is asked again at the next sync, and not
  dropped. Against cwiki.apache.org, the next sync without `--full` did not list
  the unchanged page. It never asked for the export, reported nothing, exited
  with code 0, and moved the watermark past the failure. From then on the
  refusal is silent, which is the outcome the row exists to prevent.
- **R1.19 row 6.** `export:` taken away tombstones every `<page id>.pdf` at the
  next sync. Against confluence.atlassian.com, only `--full` did.
- **Adding `export: pdf`** to a source already synced does nothing until a page
  changes version, or until `--full`. No rule claims otherwise, but a person
  adding the key would expect PDFs at the next sync.

Holding the watermark back (R2.8) does not help. The window is on the page's
modification time, and the page has not been modified.

**Proposed, in two parts.**

1. **`export` is part of what a source's configuration hash covers** (R2.3), or
   of a second hash beside it, so that adding or removing it makes the next
   sync ask for an unwindowed listing, as a changed `fields:` does. Unlike
   `fields:`, it re-evaluates what each page *carries*, not what each page
   hashes to, so it needs no page to be fetched again. The listing costs one
   request per page, and the markers decide the rest (R2.1).
2. **A page whose carried document failed at the last sync is asked what it
   carries at the next one, listed or not.** The ledger knows which item
   carried the failed key: `<page id>.pdf` names its page. This is the
   narrowest change that makes R1.20 row 3 true against a real server, and it
   costs one request per failed page per sync. That is the cost R1.20 already
   accepts ("asked again … once").

**Considered and not proposed.** Making every sync of a Confluence source
unwindowed would satisfy all three rows, and would turn the one-request sync of
task 2 into a request per page, per sync, forever. That is exactly the load this
exercise asks you not to put on someone else's server.

A test for either part needs a fake that honours the `lastmodified` clause, or
the new rows will pass for the reason the old ones do.
