# 04 · Media types, default kinds, and the file dossier will not read

**You will build:** a folder holding three kinds of file, two of which `dossier`
converts without being told anything — to two *different* kinds — and one it
refuses outright.

**You will learn:** where a media type comes from, why that table is deliberately
small, what a default kind is and why an image's is not `markdown`, and what the
repository's working agreement says to do when the honest fix is a change to
`dossier` itself.

**No model is involved.** Nothing here is installed either: exercise 03 was the
converter you write, and this one is about the decisions that happen *before* a
converter is chosen.

---

## Background, in one paragraph

A snapshot's media type is decided by `dossier` and recorded in the ledger when
the payload is fetched (R2.16). It comes from `MEDIA_TYPES` in
`src/dossier/domain/conversion.py`: a small table from extension to type, owned by
the project rather than read from the host. That is not tidiness.
`mimetypes.guess_type` is seeded from `/etc/mime.types` on Linux and from the
registry on Windows, so the same `.csv` is `text/csv` on one machine and
`application/vnd.ms-excel` on another — and that answer reaches the ledger, picks
the converter, and enters every cache key above it.

---

## Task 1 — one folder, two formats, two kinds

Build `playground/work/04/` with a source reading `inbox/notes/`, holding:

- `resources/PLAY-5001-shift-note.txt` — a plain-text shift note;
- `playground/corpus/scans/terminal-display.png` — a small photograph.

Declare the source with **no** `convert:` list, sync, and look at the ledger's
`media_type` for each. Then convert.

**Checkpoint.** Both are recognised, both convert, and the counts say nothing
interesting. Now read the two artifacts, and find the surprise:

```
PLAY-5001-shift-note.txt   text-plain     PRODUCTION INCIDENT NOTE…
terminal-display.png       png-pages      DOSSIER-PARTS 1\npage-001.png 103\n\x89PNG…
```

One is text. The other is not text at all. The source asked for nothing, so each
document got the **default kind for its own media type** — and those are not the
same kind. Find `DEFAULT_KINDS` and `FALLBACK_KIND`; the table is four lines
long, and the comment above it is the whole argument. Then ask yourself what
would have happened if an image's default had been `markdown` instead, and what
the error message would have told you to go and install.

The `DOSSIER-PARTS` header is R8.11 — a container holding one part per page,
one artifact under one key. Exercise 10 is what a step does with it.

## Task 2 — the file dossier will not read

Drop `resources/PLAY-5002-gc-pauses.log` into `inbox/notes/`, sync, and convert.

**Checkpoint.** The ledger records it as `application/octet-stream`, and convert
exits 2 over that one document while the other two — already converted, already
cached — produce nothing at all. The pair it names is `('application/octet-stream',
'markdown')`: a fallback kind on top of a media type that says only "bytes".

Before reading on, decide whether you think `.log` being absent from `MEDIA_TYPES`
is an oversight or a decision. Count how many extensions are in the table.

## Task 3 — fix it, and the exercise is choosing how

You have a choice, and the exercise is choosing well. Three candidates:

1. **Register a converter claiming `(application/octet-stream, markdown)`.**
   It would work today. What else would it claim, the first time someone drops a
   `.docx`, a `.zip` or a partially-downloaded file into the folder?
2. **Add `".log": "text/plain"` to `MEDIA_TYPES`.** That is an edit to
   `src/dossier/domain/`, and the repository's rule is unambiguous: behaviour
   that is not in a spec does not get implemented; the spec changes first, in its
   own commit, and the code follows (`CLAUDE.md`).
3. **Keep the logs out of the audited source.** Two sources, or a subfolder
   the source does not read.

Pick one, and write the argument down. If you pick 2, write the spec amendment
you would propose: which rule it touches, what the new behaviour is, an example
and a counter-example, and what would have to be true for it to be *testable*.
That is `/discover`'s job in this repository, and doing it by hand once is the
fastest way to understand why the loop is shaped the way it is.

Then read the worked precedent, because there is one. The `.png` in Task 1 used
to be `application/octet-stream` too, and this exercise used to end here, with a
proposal. That proposal is now R8.10 and R8.11 in `specs/008-conversion.md`:

```bash
git log --oneline -- specs/008-conversion.md
```

**Checkpoint.** Compare your amendment with the one that landed — not to match
it, but to see whether you covered the two questions that made the difference,
neither of which is about extensions: what the default *kind* is for the new
type, and what a stage does with an artifact that is not text. An amendment that
only adds a row to a table answers neither.

## Task 4 — the row that leaves

Take the `.log` out of `inbox/notes/` and sync again, then convert.

**Checkpoint.** The sync names the file as `tombstoned`, and convert is green:
a tombstoned row is not an input. That is the folder connector saying its
listing was complete (exercise 01, task 4; R2.21). Now suppose the source were
Jira, which narrows by `since` and cannot say that. Work out what the same
deletion would look like after a windowed sync, and which flag gets you the
tombstone without re-fetching four thousand issues (R2.22).

---

## Done when

- a ledger holding three media types, two of which you never declared anything
  about, converting to two different kinds;
- a written argument for what to do about the `.log`, in the form the repository
  actually accepts, compared against the amendment that answered the same
  question for images;
- you can say what a tombstoned row is to a run, and when a deletion is not
  tombstoned on the next sync.

**Next:** [05 · A gold set and `dossier eval`](../05-a-gold-set-and-dossier-eval/).
