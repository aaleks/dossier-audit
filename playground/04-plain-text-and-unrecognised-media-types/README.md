# 04 · Plain text, images, and media types dossier does not recognise

**You will build:** a converter for `.txt` notes, and then run into a `.png` that
`dossier` will not convert at all — and decide what the right fix is.

**You will learn:** where a media type comes from, why that table is deliberately
small, and what the repository's working agreement says to do when the honest fix
is a change to `dossier` itself.

**No model is involved.**

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

## Task 1 — a folder with a note and a photograph

Build `playground/work/04/` with a source reading `inbox/notes/`, holding:

- `resources/PLAY-3001-shift-note.txt` — a plain-text shift note;
- `playground/corpus/scans/terminal-display.png` — a small photograph.

Sync, then look at the ledger's `media_type` for each.

**Checkpoint.**

```
('PLAY-3001-shift-note.txt', 'text/plain')
('terminal-display.png',     'application/octet-stream')
```

The `.txt` has a type. The `.png` does not — it is "bytes", which is true of
anything. Before reading on, find `MEDIA_TYPES` and count how many extensions are
in it. Then decide whether you think `.png` being absent is an oversight or a
decision.

## Task 2 — convert, and read both refusals

```bash
dossier convert incident-audit
```

**Checkpoint.** Both documents are named, and the two messages differ in exactly
one way: one asks for `('text/plain', 'markdown')` and the other for
`('application/octet-stream', 'markdown')`. Same rule (R8.5), two very different
problems underneath.

## Task 3 — fix the one that is yours to fix

Write a converter claiming `(text/plain, markdown)`. It is exercise 03's shape
with a different pair and no dependencies at all — which is worth noticing beside
`pypdf`: the mechanism costs nothing when the converter is small.

Install it, convert, and read the artifact.

**Checkpoint.** The `.txt` converts. The `.png` still does not, and the run still
stops, because R8.5's blast radius is the whole run.

## Task 4 — the one that is not yours to fix

You now have a choice, and the exercise is choosing well. Three candidates:

1. **Register a converter claiming `(application/octet-stream, markdown)`.**
   It would work today. What else would it claim, the first time someone drops a
   `.docx`, a `.zip` or a partially-downloaded file into the folder?
2. **Add `".png": "image/png"` to `MEDIA_TYPES`.** That is an edit to
   `src/dossier/domain/`, and the repository's rule is unambiguous: behaviour
   that is not in a spec does not get implemented; the spec changes first, in its
   own commit, and the code follows (`CLAUDE.md`).
3. **Keep the images out of the audited source.** Two sources, or a subfolder
   the source does not read.

Pick one, and write the argument down. If you pick 2, write the spec amendment
you would propose: which rule it touches, what the new behaviour is, an example
and a counter-example, and what would have to be true for it to be *testable*.
That is `/discover`'s job in this repository, and doing it by hand once is the
fastest way to understand why the loop is shaped the way it is.

**Checkpoint.** There is a worked amendment in the solution. Compare yours with
it — not to match it, but to see whether you covered the two questions that make
the difference: what the default *kind* is for an image, and what a stage does
with an artifact that is not text.

## Task 5 — the stale row

Take the `.png` out of `inbox/notes/` and sync again, then convert.

**Checkpoint.** It still fails, on a file that is no longer there. You met the
reason in exercise 01: a folder source's deletions are not tombstoned against an
incremental listing, so the ledger row is still `active` and the document is
still held. Work out the two ways to get a green convert from here, and which one
you would use on a corpus of four thousand files.

---

## Before you finish

As in exercise 03: uninstall the converter (`uv pip uninstall
dossier-text-playground`) when you are done, or `pytest` stays red on the
acceptance test that asserts which converters a manifest recorded.

## Done when

- a `.txt` converter of your own, registered and converting;
- a written argument for what to do about the `.png`, in the form the repository
  actually accepts;
- you can say what a stale ledger row costs downstream.

**Next:** [05 · A gold set and `dossier eval`](../05-a-gold-set-and-dossier-eval/).
