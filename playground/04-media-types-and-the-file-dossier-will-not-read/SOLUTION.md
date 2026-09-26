# 04 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

Nothing is installed for this exercise. If you still have exercise 03's converter
package in the environment, uninstall it first, unless both its converters are
opt-in. One that is not claims a pair `dossier` already answers, and every
`convert` below would then refuse, although nothing here is HTML or CSV. That is
exercise 03's task 2.

```bash
mkdir -p playground/work/04/inbox/notes
cp -r playground/04-media-types-and-the-file-dossier-will-not-read/solution/workspace/. \
      playground/work/04/
cp playground/04-media-types-and-the-file-dossier-will-not-read/resources/PLAY-5001-shift-note.txt \
   playground/corpus/scans/terminal-display.png \
   playground/work/04/inbox/notes/

cd playground/work/04
../../../.venv/bin/dossier sync incident-audit
../../../.venv/bin/dossier convert incident-audit
```

---

## Task 1 — what each file is called, and what each is wanted as

```console
$ dossier sync incident-audit
shift-notes  0 known · 0 changed · 2 new -> 2 fetched
ledger updated · 2 new snapshots · 0 tombstoned

$ python -c "
import sqlite3; con = sqlite3.connect('.dossier/ledger.db')
for r in con.execute('select key, media_type, state from items order by key'): print(r)"
('PLAY-5001-shift-note.txt', 'text/plain', 'active')
('terminal-display.png', 'image/png', 'active')
```

`MEDIA_TYPES` holds fourteen extensions: `.md`, `.markdown`, `.txt`, `.pdf`,
`.jpg`, `.jpeg`, `.png`, `.html`, `.htm`, `.json`, `.csv`, `.xml`, `.yaml`,
`.yml`. Its own comment says it is "deliberately small: an extension nobody has
agreed on gets the honest answer below rather than a plausible one, and R8.5 then
reports it as unclaimed", and the paragraph above that says why the table is
owned here at all: `mimetypes.guess_type` reads `/etc/mime.types` on Linux and
`HKEY_CLASSES_ROOT` on Windows, and that answer reaches the ledger, picks the
converter and enters `K_convert`. A host-dependent guess forks every artifact
hash and every stage key above it, with nothing in any diff to explain it.

Both convert, and the summary line is unremarkable:

```console
$ dossier convert incident-audit
shift-notes  2 held · 2 converted · 0 cached
cache updated · 2 converted · 0 cached
```

The artifacts are not:

```console
$ python - <<'PY'
import json, pathlib, sqlite3
names = dict(sqlite3.connect(".dossier/ledger.db").execute("select content_hash, key from items"))
for meta in sorted(pathlib.Path(".dossier/cache/convert").rglob("*.meta.json")):
    m = json.loads(meta.read_text(encoding="utf-8"))
    art = meta.parent / meta.name[: -len(".meta.json")]
    print(f"{names[m['snapshot']]:26} {m['converter_id']:12} {art.stat().st_size:>5}  {art.read_bytes()[:40]!r}")
PY
terminal-display.png       png-pages      136  b'DOSSIER-PARTS 1\npage-001.png 103\n\x89PNG\r\n\x1a'
PLAY-5001-shift-note.txt   text-plain     472  b'PRODUCTION INCIDENT NOTE\nSite: Distribut'
```

The source declared no `convert:` list, so each document got the default kind for
its own media type — and they are different kinds. `DEFAULT_KINDS` is four lines:

```python
DEFAULT_KINDS = {
    "image/png": "page_images",
    "image/jpeg": "page_images",
}
```

Everything else falls back to `markdown`, which is the kind a stage reads and the
kind grounding searches (R6.4). An image gets a row of its own because it has no
text layer: resolving it to `markdown` would name a pair nobody can honestly
claim, and R8.5 would then send you off to install a converter that turns a
picture into text — OCR, or a captioning model, neither of which is a pure
function of the bytes. That is R8.10, and Task 3 is where it came from.

`DOSSIER-PARTS 1\npage-001.png 103\n` is R8.11: one container holding one part per
page, so a forty-page document is one artifact under one key rather than forty
that a version bump could invalidate separately. `text-plain` normalises nothing —
no line endings, no BOM, no trimming — because every one of those would change
the artifact hash for a file nobody edited, and the grounding check searches this
exact text.

## Task 2 — the file dossier will not read

```console
$ cp …/resources/PLAY-5002-gc-pauses.log inbox/notes/ && dossier sync incident-audit
shift-notes  2 known · 0 changed · 1 new -> 3 fetched
ledger updated · 1 new snapshots · 0 tombstoned

$ python -c "
import sqlite3; con = sqlite3.connect('.dossier/ledger.db')
for r in con.execute('select key, media_type from items order by key'): print(r)"
('PLAY-5001-shift-note.txt', 'text/plain')
('PLAY-5002-gc-pauses.log', 'application/octet-stream')
('terminal-display.png', 'image/png')

$ dossier convert incident-audit
1 document(s) have no converter:
  PLAY-5002-gc-pauses.log (application/octet-stream): nothing converts
  ('application/octet-stream', 'markdown'). Claimed pairs: ['(application/pdf, markdown)',
  '(application/pdf, page_images)', '(application/vnd.dossier.confluence-page+json, markdown)',
  '(application/vnd.dossier.jira-issue+json, markdown)', '(image/jpeg, page_images)',
  '(image/png, page_images)', '(text/csv, markdown)', '(text/html, markdown)',
  '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by installing
  a package that declares a dossier.converters entry point.
exit 2
```

`application/octet-stream` is the honest answer. It says "bytes", which is true of
anything, and it lets the refusal name the file rather than handing it to a
converter that was never meant to read it. The alternative — guessing
`text/plain` from four characters of filename — would be a *claim about content*
derived from a name, and R8.3's own counter-example is a file whose name lies
about what it holds.

Note what the refusal cost: the other two documents were already converted and
already cached, and this run still produced nothing and exited 2. R8.5's blast
radius is the run, not the document (exercise 03, task 1).

## Task 3 — choosing the fix

### Why not a converter for `application/octet-stream`

It would work this afternoon and be a trap by the end of the month. That pair is
every file dossier could not identify: the `.docx` someone drops in next week, a
`.zip`, a half-downloaded file. A converter claiming it would accept all of them
and produce something — most likely nonsense — for each. The refusal you are
trying to silence is the only thing standing between "we do not know what this
is" and "we audited it anyway".

### Why not just keep the logs out

Sometimes this is right, and on a real corpus it often is: a second source for
attachments, or a subfolder the audited source does not read. It costs nothing
and needs no change to `dossier`. What it does not do is make logs auditable — if
the log *is* the evidence, you have moved the problem rather than solved it.

### The amendment, if logs are evidence

This is the one the repository's working agreement points at, and writing it is
the exercise. A sketch of what a reviewable proposal looks like:

> **Amend spec 008 (conversion) and spec 002 (R2.16): recognised log media
> types.**
>
> **What changes.** `MEDIA_TYPES` gains `.log → text/plain`. A snapshot with that
> extension is recorded as `text/plain` in the ledger, and the shipped
> `text-plain` converter claims it with no further change.
>
> **What does not change.** No new converter, no new kind, and no new default: a
> log resolves to `markdown` like every other text, and R8.5 still refuses an
> extension the table does not hold.
>
> **The open question this forces.** A `.log` is often not one document. A rotated
> file is a week of unrelated events and a hundred megabytes, and a stage that is
> handed all of it grounds its spans in a haystack — the model is invited to
> quote a line from Tuesday as evidence for an incident on Friday. Recognising
> the extension is cheap; deciding what one *document* is may not be spec 008's
> question at all, but spec 002's.
>
> **Example.** `PLAY-5002-gc-pauses.log`, synced: the ledger records `text/plain`,
> `dossier convert` produces a markdown artifact through `text-plain`, and its
> text is byte-identical to the payload.
>
> **Counter-example.** A binary `.log` written by a tool that is not logging text
> at all: recorded as `text/plain`, handed to `text-plain`, and refused with
> `UnicodeDecodeError` against that one document (R8.6) rather than stopping the
> run (R8.5). That is the right blast radius, and it is worth stating that this
> amendment moves a file from the second failure into the first.
>
> **Testable as:** a unit test over `media_type_for(".log")`, and an acceptance
> test that a synced `.log` converts through `text-plain` rather than being
> refused as `application/octet-stream`.

Two things to notice about that shape. It says what does *not* change, which is
usually longer than what does. And it surfaces an open question rather than
burying it — the honest outcome may well be "this needs a decision from whoever
owns the corpus", which is a perfectly good place for a proposal to stop.

### The precedent, which is in the repository

The `.png` in Task 1 was `application/octet-stream` when this exercise was
written, and the exercise ended exactly here, with a proposal. That proposal is
now R8.10 and R8.11:

```bash
git log --oneline -- specs/008-conversion.md
```

Read them against your own. The row in `MEDIA_TYPES` was the easy half. The half
that took the work was the question the row forces and the table cannot answer:
**what is an image wanted as?** `markdown` is a promise that something produced
text; the amendment had to invent `page_images`, decide that a container is one
artifact and not forty (R8.11), say what a step receives for a non-text kind, and
then wait for a step that could read one (R3.11, R3.12) before any of it was
useful. That is why the spec changed first and in its own commit, and why the
whole of exercise 10 exists.

An amendment that only adds a row to a table answers neither of the two questions
that decide whether the row is worth anything.

## Task 4 — the row that leaves

```console
$ mkdir -p inbox/attachments && mv inbox/notes/PLAY-5002-gc-pauses.log inbox/attachments/
$ dossier sync incident-audit
shift-notes  3 known · 0 changed · 0 new -> 2 fetched
      PLAY-5002-gc-pauses.log  tombstoned
ledger updated · 0 new snapshots · 1 tombstoned

$ dossier convert incident-audit
shift-notes  2 held · 0 converted · 2 cached
cache updated · 0 converted · 2 cached
```

Green, and nothing re-converted: the two remaining documents were already in the
cache under keys that did not move. The `.log` row is still in the ledger,
`tombstoned`, and its snapshot is still in the store — a run that pinned it still
resolves (R2.7) — but a tombstoned row is not an input to the next run, so convert
has nothing to refuse.

Sync could subtract here because the folder connector declares
`lists_everything = True`: it has no change time to narrow by and returns the
whole folder every time, and a listing is complete for that reason as much as for
having been asked for with no window (R1.11, R2.21).

Jira cannot say that. It narrows its query by `since`, so a windowed listing
legitimately omits every unchanged issue, and subtracting from it would tombstone
the quiet majority of the source (R2.7 row 4). After a windowed sync the deleted
issue's row stays `active`, and the two old ways out are still bad: a fresh
workspace re-fetches everything, and a `fields` change re-evaluates everything
(R2.3). The way out now is `dossier sync --full incident-audit` — one unwindowed
listing, and the deletion is tombstoned. Version markers still skip the fetch
(R2.1), so on a quiet source of four thousand issues the flag costs one listing
and zero fetches (R2.22).

On a large corpus the standing advice is unchanged: keep the audited source
narrow enough that a stray file never lands in it. That is why this exercise puts
a log file in a folder of notes.

---

## What to take to your own project

- Decide what a file *is* in one place you own, not in a library that reads the
  host's configuration.
- "We do not recognise this" is a better answer than a plausible guess, provided
  the message names the file and the pair.
- A default is a decision, not a convenience. "What is this wanted as?" has a
  different answer for a photograph than for a note, and a single global default
  hides that until it produces a pair nobody can claim.
- When the honest fix is a change to the tool, write the proposal — including
  what does not change, and the question it forces. Half of a good amendment is
  the part that stays still.
