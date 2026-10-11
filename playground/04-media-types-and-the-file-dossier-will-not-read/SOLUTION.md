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
reports it as unclaimed". R8.5 has since been superseded, and task 2 shows by
what: such a file is still named, but it fails on its own unless its source
declared a kind (R8.25, R8.24). The paragraph above that says why the table is
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
claim, and the failure would then send you off to install a converter that turns
a picture into text — OCR, or a captioning model, neither of which is a pure
function of the bytes. Task 2 shows that failure, when a source asks for
`markdown` by name. That is R8.10, and Task 3 is where it came from.

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
shift-notes  3 held · 0 converted · 2 cached · 1 failed
    PLAY-5002-gc-pauses.log: nothing converts ('application/octet-stream', 'markdown').
    Claimed pairs: ['(application/pdf, markdown)', '(application/pdf, page_images)',
    '(application/vnd.dossier.confluence-page+json, markdown)',
    '(application/vnd.dossier.jira-issue+json, markdown)', '(image/jpeg, page_images)',
    '(image/png, page_images)', '(text/csv, markdown)', '(text/html, markdown)',
    '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by
    installing a package that declares a dossier.converters entry point.
cache updated · 0 converted · 2 cached
exit 1
```

`application/octet-stream` is the honest answer. It says "bytes", which is true of
anything, and it lets the failure name the file rather than handing it to a
converter that was never meant to read it. The alternative — guessing
`text/plain` from four characters of filename — would be a *claim about content*
derived from a name, and R8.3's own counter-example is a file whose name lies
about what it holds.

The log fails, and nothing else does. The source declared no `convert:`, so
`markdown` was `dossier`'s own choice from its default table (R8.10), made for a
file somebody dropped in a folder. Nobody asked for anything this installation
cannot do, so the log is reported the way a document a converter failed on is,
and the other two are served from cache (R8.25). The exit is 1, not 0: an audit
that covers less than its folder holds must not look clean to anything reading
`$?`. Until the file goes, or a converter for it is installed, this source
exits 1 on every run.

With the kind declared:

```console
$ dossier convert incident-audit        # convert: [markdown] added to shift-notes
2 document(s) have no converter:
  PLAY-5002-gc-pauses.log (application/octet-stream): nothing converts
  ('application/octet-stream', 'markdown'). Claimed pairs: ['(application/pdf, markdown)',
  '(application/pdf, page_images)', '(application/vnd.dossier.confluence-page+json, markdown)',
  '(application/vnd.dossier.jira-issue+json, markdown)', '(image/jpeg, page_images)',
  '(image/png, page_images)', '(text/csv, markdown)', '(text/html, markdown)',
  '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by installing
  a package that declares a dossier.converters entry point.
  terminal-display.png (image/png): nothing converts ('image/png', 'markdown'). Claimed
  pairs: ['(application/pdf, markdown)', '(application/pdf, page_images)',
  '(application/vnd.dossier.confluence-page+json, markdown)',
  '(application/vnd.dossier.jira-issue+json, markdown)', '(image/jpeg, page_images)',
  '(image/png, page_images)', '(text/csv, markdown)', '(text/html, markdown)',
  '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by installing
  a package that declares a dossier.converters entry point.
exit 2
```

Now the run stops before anything converts, and the two documents cached a
minute ago are not served either. A kind written in `convert:` is a promise the
installation has to keep, and one it cannot keep is known before any work
starts, so every document it fails is named in one refusal (R8.24). There are
two, not one. `markdown` was asked of every document the source holds, the
photograph included, and its line is task 1's question answered: the pair an
image's default would name if the default were `markdown`, and a message
sending you off to install a converter that turns a picture into text.

So the blast radius depends on who chose the kind. A file nobody asked for fails
alone. A kind the pipeline asked for, and cannot have, stops the run. Spec 008's
"Two kinds of failure" says why, and exercise 03's task 1 makes the same pair of
runs over a `.json`. The `convert:` line comes out again before task 3.

## Task 3 — choosing the fix

### Why not a converter for `application/octet-stream`

It would work this afternoon and be a trap by the end of the month. That pair is
every file dossier could not identify: the `.docx` someone drops in next week, a
`.zip`, a half-downloaded file. A converter claiming it would accept all of them
and produce something — most likely nonsense — for each. The failure you are
trying to silence is the only thing standing between "we do not know what this
is" and "we audited it anyway".

### Why not just say so in `sources.yaml`

Sometimes this is right, and task 4 does it. One line, no change to `dossier`,
and the choice is printed on every convert. The catch is the key it has to be
written under. The log has no media type of its own, only
`application/octet-stream`, which is what every file `dossier` cannot identify
is recorded as. So the line cannot say "we do not read logs". It says "we do not
read anything we cannot identify". That is candidate 1's trap in a quieter form,
and task 4 shows what else it leaves out.

### Why not just keep the logs out

Sometimes this is right too, and on a real corpus it often is: a second source
for attachments, or a subfolder the audited source does not read. Task 5 does it.
It costs nothing and needs no change to `dossier`. What neither this nor the line
above does is make logs auditable — if the log *is* the evidence, you have moved
the problem rather than solved it.

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
> log resolves to `markdown` like every other text, and an extension the table
> does not hold still fails as the `.log` does today: on its own when its kind
> was the default (R8.25), and stopping the run when a source declared it
> (R8.24).
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
> at all: recorded as `text/plain`, handed to `text-plain`, and failed as one
> document, naming `text-plain` and UTF-8 (R8.6). In a source that declares no
> `convert:` it failed alone before the amendment too, and only its reason
> changes. In a source declaring `convert: [markdown]` it used to stop the run
> (R8.24) and now fails alone. That is the right blast radius, and it is worth
> stating that this amendment moves a file from a configuration error into one
> document's failure.
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

## Task 4 — leaving it out, on purpose

Where a message below lists every claimed pair, the list is task 2's, word for
word, and is cut to `[…]`.

The extension first, because it is the key most people write:

```console
$ dossier convert incident-audit        # convert: {.log: []}
sources.yaml, line 30: in 'shift-notes', 'convert' -- Value error, convert: maps media types to kinds, and '.log' is not a media type. Write it as a snapshot records it, such as application/pdf: a file extension is not evidence about content (R8.3, R8.26).
exit 2
```

Refused at load, before anything is read. A key is a media type because the
media type is what selects a converter (R8.3), and task 1 is why `dossier` does
not let a file's name speak for its content. The key the ledger recorded for
the log is `application/octet-stream`:

```yaml
sources:
  - id: shift-notes
    type: folder
    path: inbox/notes/
    convert:
      application/octet-stream: []
```

```console
$ dossier convert incident-audit
shift-notes  3 held · 0 converted · 2 cached · 1 left out
cache updated · 0 converted · 2 cached
exit 0

$ python -c "
import sqlite3; con = sqlite3.connect('.dossier/ledger.db')
for r in con.execute('select key, media_type, state from items order by key'): print(r)"
('PLAY-5001-shift-note.txt', 'text/plain', 'active')
('PLAY-5002-gc-pauses.log', 'application/octet-stream', 'active')
('terminal-display.png', 'image/png', 'active')
```

Exit 0, and the log is not a failure. It is still held: its row is `active`, and
its snapshot is in the store. A media type mapped to no kinds is not converted,
and no step reads it (R8.27). The note and the photograph are not named in the
map, so each gets its default kind as before (R8.26), and both are served from
cache. `1 left out` is counted apart from the failures, and it is on every
convert from now on. The source said it does not read this, and the output keeps
saying so.

Now a file you did not think about:

```console
$ cp …/resources/PLAY-5003-shift-handover.docx inbox/notes/ && dossier sync incident-audit
shift-notes  3 known · 0 changed · 1 new -> 4 fetched
ledger updated · 1 new snapshots · 0 tombstoned

$ python -c "
import sqlite3; con = sqlite3.connect('.dossier/ledger.db')
for r in con.execute('select key, media_type, state from items order by key'): print(r)"
('PLAY-5001-shift-note.txt', 'text/plain', 'active')
('PLAY-5002-gc-pauses.log', 'application/octet-stream', 'active')
('PLAY-5003-shift-handover.docx', 'application/octet-stream', 'active')
('terminal-display.png', 'image/png', 'active')

$ dossier convert incident-audit
shift-notes  4 held · 0 converted · 2 cached · 2 left out
cache updated · 0 converted · 2 cached
exit 0
```

The handover is left out too, and nothing names it. The count went from 1 to 2,
and that is the only sign. What it says:

```console
$ python - <<'PY'
import re, zipfile
xml = zipfile.ZipFile("inbox/notes/PLAY-5003-shift-handover.docx").read("word/document.xml").decode()
for para in re.findall(r"<w:p>(.*?)</w:p>", xml):
    print(re.sub(r"<[^>]+>", "", para))
PY
SHIFT HANDOVER
Service: orders-api, eu-west-1
Date: 2026-06-14, night shift
Between 02:12 and 02:14 the orders-api node in eu-west-1a stopped answering searches during repeated full garbage-collection pauses. The node was drained at 02:13 and traffic shifted to eu-west-1b.
Severity: major. 37 orders were not accepted in the window; the customer desk refunded CHF 1850 in delivery fees the same morning.
Follow-up: heap sizing review for orders-api, owner platform team.
```

A major incident with a loss in Swiss francs, which is exactly what
`incident-audit` asks for, and no run will read it. `.docx` is not in
`MEDIA_TYPES`, so the ledger records the handover as `application/octet-stream`,
the same media type as the log. `convert:` is keyed by media type, so the line
you wrote about the log was never about the log. `application/octet-stream` is
not a type of file. It is `dossier` saying "I could not identify this", and a
source that leaves it out leaves out every file nobody could identify: today's
log, this handover, and next month's `.zip`, all counted and none named.

That is the trade-off, stated plainly. R8.27 says that a new kind of attachment
is reported the first time it arrives, because a file whose media type nobody
named still fails. That holds for every media type except the one you just
named. Once `application/octet-stream` is left out, an unidentified file is
never new again. The line is right for a folder where unidentified files are
noise, and wrong for one where they might be evidence. This folder is the second
kind.

The file `dossier` *can* identify behaves differently:

```console
$ cp …/03-html-exports-and-a-converter-you-write/resources/PLAY-4006-indexer-alerts.json inbox/notes/ && dossier sync incident-audit
shift-notes  4 known · 0 changed · 1 new -> 5 fetched
ledger updated · 1 new snapshots · 0 tombstoned

$ dossier convert incident-audit
shift-notes  5 held · 0 converted · 2 cached · 1 failed · 2 left out
    PLAY-4006-indexer-alerts.json: nothing converts ('application/json', 'markdown'). Claimed pairs: […]. A converter is added by installing a package that declares a dossier.converters entry point.
cache updated · 0 converted · 2 cached
exit 1
```

`.json` is in `MEDIA_TYPES`, so the alert export is `application/json`, a media
type the map does not name. Its kind is the default, `markdown`, nothing claims
that pair, and it fails on its own, by name (R8.25, R8.26 row 3). It is exercise
03's task 1 again, with a map in the source that says nothing about it. What
separates the two new files is not the map. It is whether `dossier` could say
what the file was.

**Optional: saying what the photograph is wanted as.**

```console
$ dossier convert incident-audit        # image/png: [page_images] added to the map
shift-notes  5 held · 0 converted · 2 cached · 1 failed · 2 left out
    PLAY-4006-indexer-alerts.json: nothing converts ('application/json', 'markdown'). Claimed pairs: […]. A converter is added by installing a package that declares a dossier.converters entry point.
cache updated · 0 converted · 2 cached
exit 1

$ dossier convert incident-audit        # image/png: [markdown] instead
1 document(s) have no converter:
  terminal-display.png (image/png): nothing converts ('image/png', 'markdown'). Claimed pairs: […]. A converter is added by installing a package that declares a dossier.converters entry point.
exit 2
```

`page_images` is the photograph's default anyway, so writing it down re-converts
nothing: the convert key holds the snapshot, the converter and its options, and
not how the kind was chosen (spec 005). What changes is who chose it. The pair
is now declared, so an installation that could not make it would stop the run
(R8.24) rather than fail the photograph alone (R8.25).

Asked for `markdown`, the photograph stops the run, and it is the only document
named. Task 2's `convert: [markdown]` named the log as well, because a list asks
every document for every kind. The map asks `markdown` of PNGs and of nothing
else: the log is left out and the note keeps its default. The alert export's
failure is not in the refusal either. It is a default-kind failure, reported
per document while converting, and a refusal stops before anything converts.

This is the part of the map that fits the exercise's lesson. Written out for
every media type the folder holds, it is one place you own that says what each
kind of file is wanted as, or that it is not wanted. The `application/octet-stream`
line is the one entry in it that is not about a kind of file.

## Task 5 — the row that leaves

```console
$ mkdir -p inbox/attachments
$ mv inbox/notes/PLAY-5002-gc-pauses.log inbox/notes/PLAY-5003-shift-handover.docx \
     inbox/notes/PLAY-4006-indexer-alerts.json inbox/attachments/
$ dossier sync incident-audit        # convert: taken out of shift-notes
shift-notes  5 known · 0 changed · 0 new -> 2 fetched
      PLAY-4006-indexer-alerts.json  tombstoned
      PLAY-5002-gc-pauses.log  tombstoned
      PLAY-5003-shift-handover.docx  tombstoned
ledger updated · 0 new snapshots · 3 tombstoned

$ python -c "
import sqlite3; con = sqlite3.connect('.dossier/ledger.db')
for r in con.execute('select key, media_type, state from items order by key'): print(r)"
('PLAY-4006-indexer-alerts.json', 'application/json', 'tombstoned')
('PLAY-5001-shift-note.txt', 'text/plain', 'active')
('PLAY-5002-gc-pauses.log', 'application/octet-stream', 'tombstoned')
('PLAY-5003-shift-handover.docx', 'application/octet-stream', 'tombstoned')
('terminal-display.png', 'image/png', 'active')

$ dossier convert incident-audit
shift-notes  2 held · 0 converted · 2 cached
cache updated · 0 converted · 2 cached
exit 0
```

Green, and nothing re-converted: the two remaining documents were already in the
cache under keys that did not move. The three rows are still in the ledger,
`tombstoned`, and their snapshots are still in the store — a run that pinned one
still resolves (R2.7) — but a tombstoned row is not an input to the next run, so
nothing fails, and the three are not even counted as held.

Compare the log's row with task 4's. Left out, it was `active`: held, counted on
every convert, and skipped because the source said so. Tombstoned, it is gone
from the source, and the source says nothing about it or about any media type.
So the next `.docx` somebody drops into `inbox/notes/` fails on its own, by name,
and the exit is 1, as the log did in task 2. That is the better answer for a
folder of notes, and the reason this solution's `sources.yaml` ends with no
`convert:` at all.

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
- Leaving something out should be a declaration, visible in every report, and
  never a default. Check what the declaration is keyed on: leaving out
  "unknown" leaves out everything unknown, including what you have not seen yet.
- When the honest fix is a change to the tool, write the proposal — including
  what does not change, and the question it forces. Half of a good amendment is
  the part that stays still.
