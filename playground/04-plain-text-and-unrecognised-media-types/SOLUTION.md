# 04 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

```bash
VIRTUAL_ENV=$PWD/.venv uv pip install --no-deps -e \
  playground/04-plain-text-and-unrecognised-media-types/solution/dossier_text_playground

mkdir -p playground/work/04/inbox/notes
cp -r playground/04-plain-text-and-unrecognised-media-types/solution/workspace/. playground/work/04/
cp playground/04-plain-text-and-unrecognised-media-types/resources/PLAY-3001-shift-note.txt \
   playground/work/04/inbox/notes/
cp playground/corpus/scans/terminal-display.png playground/work/04/inbox/notes/

cd playground/work/04
../../../.venv/bin/dossier sync incident-audit
../../../.venv/bin/dossier convert incident-audit    # still exits 2 — that is task 4
```

---

## Task 1 — what each file is called

```console
$ dossier sync incident-audit
shift-notes  0 known · 0 changed · 2 new -> 2 fetched
ledger updated · 2 new snapshots · 0 tombstoned

$ python -c "
import sqlite3; con = sqlite3.connect('.dossier/ledger.db')
for r in con.execute('select key, media_type from items'): print(r)"
('PLAY-3001-shift-note.txt', 'text/plain')
('terminal-display.png', 'application/octet-stream')
```

`MEDIA_TYPES` holds eleven extensions: `.md`, `.markdown`, `.txt`, `.pdf`,
`.html`, `.htm`, `.json`, `.csv`, `.xml`, `.yaml`, `.yml`. Its own comment says it
is "deliberately small: an extension nobody has agreed on gets the honest answer
below rather than a plausible one".

`application/octet-stream` is that honest answer. It says "bytes", which is true
of anything, and it lets the refusal name the file rather than handing it to a
converter that was never meant to read it. The alternative — guessing `image/png`
from three characters of filename — would be a *claim about content* derived from
a name, and R8.3's own counter-example is a file whose name lies about what it
holds.

## Task 2 — two refusals that look alike

```console
$ dossier convert incident-audit
2 document(s) have no converter:
  PLAY-3001-shift-note.txt (text/plain): nothing converts ('text/plain', 'markdown').
  Claimed pairs: ['(text/markdown, markdown)']. …
  terminal-display.png (application/octet-stream): nothing converts
  ('application/octet-stream', 'markdown'). Claimed pairs: ['(text/markdown, markdown)']. …
exit 2
```

Same rule, two different underlying problems:

- **`text/plain`** — dossier knows exactly what this is. Nobody has written the
  converter. That is a gap you can close from outside, and task 3 closes it.
- **`application/octet-stream`** — dossier does not know what this is. No
  converter you write can honestly claim that pair, because that pair is not "a
  PNG", it is "anything we could not identify".

## Task 3 — the converter that is yours to write

`solution/dossier_text_playground/` is the whole package:

```toml
[project]
name = "dossier-text-playground"
dependencies = []

[project.entry-points."dossier.converters"]
text-plain = "dossier_text_playground.plain:PlainTextConverter"
```

```python
class PlainTextConverter:
    id = "text-plain"
    version = "1.0.0"
    media_type = "text/plain"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"{self.id} was given bytes that are not valid UTF-8 "
                f"({error.reason} at byte {error.start})"
            ) from error
        return text.encode("utf-8")
```

Nearly the same code as the `markdown-text` converter dossier ships, and that is
the point: the pair is `(media type, kind)`, so claiming `text/markdown` says
nothing about a `.txt` file. Two claims, one behaviour.

No line endings normalised, no BOM stripped, no whitespace trimmed. Every one of
those would change the artifact hash for a file nobody edited, and the grounding
check searches this exact text.

With the `.png` moved out of the way (task 5) it converts:

```console
$ dossier convert incident-audit
shift-notes  1 held · 1 converted · 0 cached
cache updated · 1 converted · 0 cached

$ cat .dossier/cache/convert/a7/a5/a7a587d6…
PRODUCTION INCIDENT NOTE
Site: Distribution Centre 2
Severity: minor
…
```

## Task 4 — the one that is not yours to fix

### Why not a converter for `application/octet-stream`

It would work this afternoon and be a trap by the end of the month. That pair is
every file dossier could not identify: the `.docx` someone drops in next week, a
`.zip`, a half-downloaded file. A converter claiming it would accept all of them
and produce something — most likely nonsense — for each. The refusal you are
trying to silence is the only thing standing between "we do not know what this
is" and "we audited it anyway".

### Why not just keep images out

Sometimes this is right, and on a real corpus it often is: a second source for
attachments, or a subfolder the audited source does not read. It costs nothing
and needs no change to `dossier`. What it does not do is make images auditable —
if the photograph *is* the evidence, you have moved the problem rather than
solved it.

### The amendment, if images are evidence

This is the one the repository's working agreement points at, and writing it is
the exercise. A sketch of what a reviewable proposal looks like:

> **Amend spec 008 (conversion) and spec 002 (R2.16): recognised image media
> types.**
>
> **What changes.** `MEDIA_TYPES` gains `.png → image/png`, `.jpg`/`.jpeg` →
> `image/jpeg` and `.tif`/`.tiff` → `image/tiff`. A snapshot with one of those
> types is recorded under it in the ledger, exactly as `.pdf` is today.
>
> **What does not change.** No converter for those types ships with `dossier`. An
> image with no installed converter is still refused by R8.5, and the message
> still names the pair — but the pair is now `('image/png', …)`, which a
> third-party package can honestly claim.
>
> **The open question this forces, and it is the real content of the amendment:**
> what is the default *kind* for an image? `markdown` is the default for every
> media type today (`DEFAULT_KIND`), and an image converted to the `markdown`
> kind is a claim that something produced text from it — an OCR pass, or a
> captioning model. For a captioning model the artifact is no longer a pure
> function of the bytes unless the model is pinned and the answer cached like any
> other stage, which is spec 005's territory and not spec 008's. Spec 008 already
> records the default kind for non-PDF media types as OPEN; this amendment cannot
> land without closing it.
>
> **Example.** `terminal-display.png`, synced: the ledger records `image/png`;
> `dossier convert` refuses it naming `('image/png', 'markdown')` and the claimed
> pairs; installing a package claiming that pair converts it and nothing else
> changes.
>
> **Counter-example.** A file named `report.png` that is actually a PDF: still
> recorded as `image/png`, because the table is about names and R8.3 already says
> a name is not evidence about content. If that matters, it is a different
> amendment — sniffing bytes — with different costs.
>
> **Testable as:** a unit test over `media_type_for` for each new extension, and
> an acceptance test that a synced `.png` is refused by name rather than as
> `application/octet-stream`.

Two things to notice about that shape. It says what does *not* change, which is
usually longer than what does. And it surfaces an open question rather than
burying it — the honest outcome of this exercise may well be "this needs a
decision from whoever owns the corpus", which is a perfectly good place for a
proposal to stop.

## Task 5 — the stale row

```console
$ mkdir -p inbox/attachments && mv inbox/notes/terminal-display.png inbox/attachments/
$ dossier sync incident-audit
shift-notes  2 known · 0 changed · 0 new -> 1 fetched
ledger updated · 0 new snapshots · 0 tombstoned

$ dossier convert incident-audit
1 document(s) have no converter:
  terminal-display.png (application/octet-stream): …
exit 2
```

The file is gone and the run still fails on it. The ledger row is still `active`,
because a folder source's departures are only computed against a full listing and
this listing was incremental (exercise 01, task 4; R2.7 row 4).

Two ways out:

1. **A fresh workspace** — delete `.dossier/` and sync again. On four documents
   that is free. On four thousand it re-fetches and re-hashes the whole corpus,
   and on a metered API it is a bill.
2. **Force a full listing** — change the source's projection so sync
   re-evaluates it (R2.3). Cheaper in ceremony, but it re-fetches everything too,
   and changing `fields` on a folder source has its own consequences.

On a large corpus the real answer is neither: it is to know this property before
you need it, and to keep the audited source narrow enough that a stray file never
lands in it. That is why this exercise puts a photograph in a folder of notes.

---

## What to take to your own project

- Decide what a file *is* in one place you own, not in a library that reads the
  host's configuration.
- "We do not recognise this" is a better answer than a plausible guess, provided
  the message names the file and the pair.
- When the honest fix is a change to the tool, write the proposal — including
  what does not change, and the question it forces. Half of a good amendment is
  the part that stays still.
