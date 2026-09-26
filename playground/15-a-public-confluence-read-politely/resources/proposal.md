# Two proposals from exercise 15, and how they were settled

Exercise 15 found two things `dossier` did against a real Confluence that its
specs said, or implied, it should not. Each was written up here as a proposal,
and both were accepted in a different form. Behaviour that is not in a spec does
not get implemented (`CLAUDE.md`), so each became rules first:

| Proposal | Became | What dossier does now |
|---|---|---|
| 1. A step is not called for a document that has none of the kind it reads | **R6.21** | `extract` reading `documents` does not run for a PNG. No call, no artifact, no cache entry (task 4) |
| 2. A page is asked what it carries when that may have changed | **R2.23** and **R2.24** | A refused export is owed, and asked for at every sync until it is stored. A change to `export:`, or to any key of the source's own, lists the source whole at the next sync (tasks 6 and 7) |

Read each proposal as it was written, then read the rule, and find what changed
on the way. The notes under each heading say what to look for. The proposals
are kept as they were written, apart from these notes, the way exercise 11 keeps
its own.

---

## 1. A step is not called for a document that has none of the kind it reads

> **Settled as R6.21**, a rule of its own beside R6.13, rather than an extension
> of it. The core is what was proposed: no model call, no artifact and no cache
> entry for such a document, and replay skips it as the run did (R4.7). Two
> things differ:
>
> - **It is not reported as skipped.** The step line counts the documents the
>   step ran for, `extract: 2 document(s)`. The two PNGs appear in the plan's
>   count (`4 document(s)`) and in the manifest's documents, and nowhere under
>   `extract`. The proposal wanted a line naming each one. The rule decided
>   that a document a step never had anything to read is not news.
> - **Its scope is stated per mode.** A `per_part` step already had nothing to
>   fan out over, and an `aggregate` step reads a set that such a document is
>   simply not in. So the rule is about the mode that was wrong, `per_file`, and
>   says why the other two were already right.

**Found in task 4.** `extract` reads bare `documents`, which is
`documents@markdown` (R3.11). A Confluence page's PNGs convert to `page_images`
by default (R8.10), and a run's documents are every document that converted, in
whatever kind (R6.15). So `extract` was called for each PNG, and each call's
prompt had an empty string where the document should be. Two things followed:

- **A call was paid for about nothing.** A real model answers something, and a
  careful one answers nulls. Either way the answer was cached and served again.
- **Two such documents shared one stage key.** The input of both was `""`, so
  the second was served the first's answer, and that answer named the first
  document's key. `zstd-1.3.4.png.json` said it was about
  `zstd-1.3.3-vs-4.png`.

R6.13 already named this failure in its own reasoning, for a document that an
earlier *step* produced nothing for: "asks a model about a document nobody
read, pays for the call, and caches an answer under a key whose input hash is
the hash of `""`". It did not cover a document that has no artifact of the kind
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
would be needed however open question 5 is answered. *(Still true. Open
question 5 was answered later, by R8.26 and R8.27, and R6.21 was needed all the
same. Task 8 shows the two together.)*

---

## 2. A page is asked what it carries when what it carries may have changed

> **Settled as two rules**, R2.23 and R2.24, each wider than the part of the
> proposal it came from.
>
> - **Part 2 became R2.23**, for any key whose fetch failed, not only a page's
>   export. The key is recorded in a ledger table of its own, `owed`, with the
>   item that carries it (`look.py owed` shows it). At every sync, an owed key's
>   item is visited whether the listing returned it or not. An owed item is
>   fetched. For an owed file, its item's files are listed again, and the item
>   is not fetched unless its own marker moved. A key stops being owed when it
>   is stored, when its item stops carrying it, or when a complete listing drops
>   its item.
> - **Part 1 became R2.24**, for every key the connector declares, not only
>   `export`: `url`, `query`, a folder's `path`. Their hash is recorded apart
>   from R2.3's projection hash, so that a change lists the source whole, as
>   `--full` does, without fetching any item whose marker has not moved. A
>   change to `fields:` is still R2.3's re-evaluation, which fetches every item.
>
> The warning at the end of this proposal was taken as well. The tests for both
> rules use a stand-in that honours the listing window, as a real server does.

**Found in tasks 6 and 7.** `attachments(key)` is asked only for a page the
listing returns, and an incremental listing returns only pages modified inside
the window (R1.4, R1.15 row 2). Two rules assumed otherwise. Both held in their
unit tests, whose fake server returned the page whatever the window, and a
third case was covered by no rule at all:

- **R1.20 row 3.** A refused export is asked again at the next sync, and not
  dropped. Against cwiki.apache.org, the next sync without `--full` did not list
  the unchanged page. It never asked for the export, reported nothing, exited
  with code 0, and moved the watermark past the failure. From then on the
  refusal was silent, which is the outcome the row exists to prevent.
- **R1.19 row 6.** `export:` taken away tombstones every `<page id>.pdf` at the
  next sync. Against confluence.atlassian.com, only `--full` did.
- **Adding `export: pdf`** to a source already synced did nothing until a page
  changed version, or until `--full`. No rule claimed otherwise, but a person
  adding the key would expect PDFs at the next sync.

Holding the watermark back (R2.8) did not help. The window is on the page's
modification time, and the page had not been modified.

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
