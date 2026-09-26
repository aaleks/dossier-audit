# 04 · Media types, default kinds, and the file dossier will not read

**You will build:** a folder holding three kinds of file, two of which `dossier`
converts without being told anything — to two *different* kinds — and one it
will not read at all.

**You will learn:** where a media type comes from, why that table is deliberately
small, what a default kind is and why an image's is not `markdown`, why a file
nothing reads fails on its own until a source asks for its kind and then stops
the run, how a source says which media types it does not read and what leaving
out "unknown" costs, and what the repository's working agreement says to do when
the honest fix is a change to `dossier` itself.

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

**Checkpoint.** The ledger records it as `application/octet-stream`. Convert
reports `3 held · 0 converted · 2 cached · 1 failed` and exits 1. The log fails
on its own, naming the pair `('application/octet-stream', 'markdown')`: a
fallback kind on top of a media type that says only "bytes". The other two are
served from cache.

The source asked for no kind, so `dossier` chose one from its table, for a file
somebody dropped in a folder. Nobody asked for anything this installation cannot
do, so the rest of the folder is audited and the log is named as missing. Now
ask. Add `convert: [markdown]` to the source, and convert again.

**Checkpoint.** Exit 2, and nothing is converted or served from cache. Two
documents are named, not one: the log, and the photograph as
`('image/png', 'markdown')`. A kind written in `convert:` is asked of every
document the source holds, and one this installation cannot make is known
before any work starts. The photograph's line also answers task 1's question: it
is the pair an image's default would name if the default were `markdown`, and
it sends you off to install a converter that turns a picture into text.

Same file, same installation, and one line decided whether it failed alone or
stopped everything. Find out why in spec 008's "Two kinds of failure", and in
R8.24 and R8.25. Then take the `convert:` line out again.

Before reading on, decide whether you think `.log` being absent from `MEDIA_TYPES`
is an oversight or a decision. Count how many extensions are in the table.

## Task 3 — fix it, and the exercise is choosing how

You have a choice, and the exercise is choosing well. Four candidates:

1. **Register a converter claiming `(application/octet-stream, markdown)`.**
   It would work today. What else would it claim, the first time someone drops a
   `.docx`, a `.zip` or a partially-downloaded file into the folder?
2. **Add `".log": "text/plain"` to `MEDIA_TYPES`.** That is an edit to
   `src/dossier/domain/`, and the repository's rule is unambiguous: behaviour
   that is not in a spec does not get implemented; the spec changes first, in its
   own commit, and the code follows (`CLAUDE.md`).
3. **Say in `sources.yaml` that the source does not read it.** `convert:` can
   map a media type to the kinds a source wants of it, and to none at all
   (R8.26, R8.27). Task 4 tries it.
4. **Keep the logs out of the audited source.** Two sources, or a subfolder
   the source does not read. Task 5 tries it.

Pick one before you try any, and write the argument down. Tasks 4 and 5 may
change your mind, and that is fine. If you pick 2, write the spec amendment
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

## Task 4 — leaving it out, on purpose

Candidate 3. `convert:` has a second form besides the list: a map from a media
type to the kinds the source wants of it (R8.26). A media type mapped to no kinds
at all is not read (R8.27). Say that of the log.

Your first try will probably name the file's extension, `.log: []`. Try it, and
read why it is refused. Then write the key the ledger recorded for the log in
task 2:

```yaml
    convert:
      application/octet-stream: []
```

**Checkpoint.** `3 held · 0 converted · 2 cached · 1 left out`, and exit 0. Look
at the ledger: the log's row is still `active`. It is synced and held like any
other file. Nothing converts it, and no step will read it. Every convert counts
it apart from the failures, so the decision shows up wherever the counts do.

Now the cost. Drop `resources/PLAY-5003-shift-handover.docx` into
`inbox/notes/`, sync, and convert.

**Checkpoint.** `4 held · 0 converted · 2 cached · 2 left out`, and still exit 0.
Read the handover (open it in a word processor, or see `SOLUTION.md` for a
four-line reader). It covers the night the log records, and it states a
severity and a loss. You never mentioned a `.docx`, so why was it left out? Look
at its row in the ledger.

Then drop exercise 03's `resources/PLAY-4006-indexer-alerts.json` in as well,
sync, and convert.

**Checkpoint.** This one is not left out. It fails on its own, named, and the exit
is 1. The map named one media type and not two, so what makes the handover and
the alert export different? Exercise 03's task 1 made the same JSON fail.

**Optional.** A map can also say what a media type *is* wanted as. Add
`image/png: [page_images]` under the same `convert:`, and convert. Then change it
to `image/png: [markdown]`, and convert again.

**Checkpoint.** The first changes nothing: `0 converted`, because the convert
key holds the pair and not how the kind was chosen. The second exits 2 and names
one document. Task 2's `convert: [markdown]` named two. Why one now, and why is
the alert export's failure not in the refusal? Put `page_images` back, or take
the line out, before you go on.

## Task 5 — the row that leaves

Candidate 4. Take the `convert:` map out of the source. Make `inbox/attachments/`
next to `inbox/notes/`, and move the three files that are not shift notes into
it: the log, the handover and the alert export. Sync again, then convert.

**Checkpoint.** The sync names all three files as `tombstoned`, and convert is
green: a tombstoned row is not an input. That is the folder connector saying its
listing was complete (exercise 01, task 4; R2.21). Compare the log's ledger row
now with its row in task 4, where it was left out. Neither convert reads it.
Which of the two setups would name the next `.docx` somebody drops into
`inbox/notes/`?

Now suppose the source were Jira, which narrows by `since` and cannot say its
listing was complete. Work out what the same deletion would look like after a
windowed sync, and which flag gets you the tombstone without re-fetching four
thousand issues (R2.22).

---

## Done when

- a ledger holding three media types, two of which you never declared anything
  about, converting to two different kinds;
- you can say why the same `.log` failed on its own in one run and stopped the
  next, and what changed in between;
- a written argument for what to do about the `.log`, in the form the repository
  actually accepts, compared against the amendment that answered the same
  question for images;
- you left the log out on purpose and saw what else went with it. You can say
  why the handover was left out without a word while the alert export failed by
  name;
- you can say what a tombstoned row is to a run, how it differs from a row left
  out, and when a deletion is not tombstoned on the next sync.

**Next:** [05 · A gold set and `dossier eval`](../05-a-gold-set-and-dossier-eval/).
