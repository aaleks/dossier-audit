# 18 · A website, read as documents

**You will build:** a workspace holding three public websites as documents: a
documentation site read from its sitemap, a site with no sitemap read by
following its links, and a site whose pages are written by a script, drawn by a
headless browser.

**You will learn:** what the `web` connector lists, what it holds, and what a
stage is shown:

- how a sitemap's `<lastmod>` spares a sync from fetching;
- why the note of a page is its `<main>` and not the whole page;
- why a crawl that cannot finish lists nothing rather than a part;
- how a source whose listing fails leaves the others to sync;
- what a browser adds to a page, and what it is not allowed to ask for.

**Needs network access, and reads sites that belong to other people. No model,
no key, no Docker. Task 4 needs `dossier[browser]` and a headless Chromium.**

---

## Read this before you start

Every exercise but 11 and 15 runs offline. This one reads three public sites
anonymously: `docs.astral.sh` (uv's documentation), `www.python.org`, and
`quotes.toscrape.com`, a sandbox that exists to be read by programs like this
one. You are a guest on all three:

- **The scopes are narrow.** Ten pages of uv's documentation, seven of
  python.org's, eleven of the quotes site. Do not widen a `url` to see what
  happens: `https://www.python.org/` is thousands of pages, and a crawl asks
  every one of them.
- **Nothing you run can change a page.** Every request is a `GET` (R1.1), and a
  browser drawing a page is refused anything else (R1.41).
- **A site that says slow down is listened to.** A `429` ends the sync's
  requests to that site (R1.35), and `delay:` spaces them (R1.36). Task 3 uses
  it.

Sites change. A page edited since this was written will have another
`<lastmod>`, another snapshot address, and perhaps another note. `SOLUTION.md`
marks each block **[run]**, **[derived]** or **[shape]**, as exercises 11 and
15 do.

---

## Background, in one paragraph

`web` is the fourth connector that ships with `dossier`, and
`docs/web-connector.md` is the tour of it. A source is a `url`, read as a
prefix. It is listed from the site's sitemap (R1.29), or, when the source says
`crawl:`, by following its links (R1.37). A page's key is its URL relative to
`url`, with `index` for a directory (R1.30). Its marker is its sitemap
`<lastmod>`, and a crawled page has none (R1.31). It is held as the site sent
it, or, when the source says `render: browser`, as a headless Chromium draws it
(R1.40). `html-markdown` writes the note a stage reads, and writes only the
page's `<main>`, when the page declares one (R8.33).

---

## Setup

From the repository root:

```bash
uv sync --all-extras --no-extra docling      # or: pip install -e ".[browser]"
mkdir -p playground/work/18
cp -r playground/18-a-website-read-as-documents/solution/workspace/pipelines playground/work/18/
cd playground/work/18

# the helper that reads the ledger, the snapshots and the notes; it only reads
L="../../../.venv/bin/python ../../18-a-website-read-as-documents/resources/look.py"
```

`site-audit` is copied rather than written, because it is not what this exercise
is about: nothing in it runs a model, and `dossier sync` and `dossier convert`
take a pipeline only to know which sources to read. Its `sources:` line names
all three sites. Until task 3, cut it down to the ones `sources.yaml` holds, or
the pipeline is refused for naming sources that do not exist.

## Task 1 — a sitemap, and what a second sync costs

Write `sources.yaml` yourself, from `docs/web-connector.md`. It has one `web`
source, `uv-projects`, whose `url` is
`https://docs.astral.sh/uv/concepts/projects/`. uv publishes its sitemap at
`https://docs.astral.sh/uv/sitemap.xml`, not at the host's root, so say where.
Set the pipeline's `sources:` to `[uv-projects]`.

```bash
dossier sync site-audit
$L ledger
$L watermarks
dossier sync site-audit
```

**Checkpoint.** The first sync holds ten pages; the second fetches none:
`10 known · 0 changed · 0 new -> 0 fetched`. Work out each of these:

- **The keys.** `index`, `build/index`, `config/index`… Why does every key but
  one end in `index`, and why is `url`'s own page not keyed `""` (R1.30)?
- **The markers.** Every page's marker is the same date. Open the sitemap and
  find it. What does a sitemap generator that stamps every page with the build
  date cost a sync, and why is that still safe (R1.31, R1.4)?
- **The second sync.** How many requests did it make? It read `robots.txt`
  (absent: `404` allows everything, R1.33) and the sitemap. Why did it not ask
  for a single page (R2.1)?

## Task 2 — what was held, and what a stage will read

```bash
dossier convert site-audit
P=$($L payload uv-projects/index)
$L note uv-projects/index > index.md
wc -c $P index.md
```

`$P` is the page as the site sent it (R1.43), and `index.md` is the note a
stage would be shown. Read both, then check each of these:

- **Most of the page is the site.** Count the `<nav>` elements in `$P`, and
  find the search box and the footer. None of them is in the note. Find the
  `<main>` in `$P`, and read R8.33 for what is written of it and what is taken
  from inside it.
- **Nothing is chosen by guesswork.** What would a page that declares no
  `<main>` look like as a note? Look at `PLAY-4001` in exercise 3 (R8.21 row 1).
  Why is a class name like `md-sidebar` never read?
- **What stayed.** The note ends with a date and `Back to top`. Find both in
  `$P`, and say why they are in the note. Where is the line between what a
  page's author put in `<main>` and what a reader would call content?

## Task 3 — a site with no sitemap

Add a second source, `python-about`, with `url: https://www.python.org/about/`
and nothing else. Put it first in the pipeline:
`sources: [python-about, uv-projects]`.

```bash
dossier sync site-audit; echo "exit $?"
```

**Checkpoint.** `python-about: listing failed:`, naming `sitemap.xml` and `404`,
then `uv-projects` synced as before, and exit code `1`. python.org has no
sitemap, and its `robots.txt` names none. Why is a sitemap that cannot be read a
failed listing and not an empty one (R1.29 row 6, R2.7)? Before R2.27, the same
failure was a traceback, and `uv-projects` was never synced.

Now let it crawl, but too little: `crawl: 5`.

```bash
dossier sync site-audit; echo "exit $?"
```

**Checkpoint.** The listing fails again, naming `…/about/legal/`, the URL it
had no room left to ask. Why does a crawl that stops at its limit list nothing,
rather than the five pages it did read (R1.38)? What would the next sync have
done to the rest?

Give it room, and a pace: `crawl: 20` and `delay: 0.5`.

```bash
time dossier sync site-audit
$L ledger python-about
dossier sync site-audit
```

**Checkpoint.** Seven pages, each keyed as a sitemap's would be, and no markers.
The second sync reports `7 fetched` and writes nothing. Where did those seven
pages come from, if nothing was asked for twice (R1.37 row 2)? Why is there no
default for `crawl:` (R1.39)? About how long should a sync of seven pages take
with `delay: 0.5`, counting `robots.txt`?

## Task 4 — a page drawn by its script

Install the browser once, from the repository root, if you have not:

```bash
playwright install chromium-headless-shell   # about 115 MB; dossier never downloads it
```

Add `quotes`: `url: https://quotes.toscrape.com/js/` and `crawl: 12`, and add it
to the pipeline's `sources:`.

```bash
dossier sync site-audit
dossier convert site-audit
$L note quotes/index
grep -c "Albert Einstein" $($L payload quotes/index)
```

**Checkpoint.** Eleven pages, and the note of `index` has the site's name, a
login link and `Next →`, and not one quote. Yet `Albert Einstein` is in the
payload. Find where, and say why `html-markdown` never writes it (R8.21).

Now add `render: browser` to `quotes`.

```bash
dossier sync site-audit
dossier convert site-audit
$L note quotes/index | head -20
head -c 3 $($L payload quotes/index) | od -An -tx1
dossier sync site-audit
```

**Checkpoint.** `11 changed`, each with both addresses, and the note is the
quotes. The payload starts `ef bb bf`. The third sync writes nothing. Work out:

- **Who asked for what.** The page was asked for once, by `dossier`. Which
  requests did the browser make, and which were refused (R1.41)? Why is an
  image never asked for, and why would a script's `POST` never be sent?
- **Why a byte-order mark.** A drawn page still carries the
  `<meta charset>` the site wrote. Read R1.40 for why it is held in UTF-8
  behind a mark, and not in the charset the page declared.
- **Why eleven changed.** Adding `render:` changed what a fetch returns. Why was
  every page fetched here without any help? Keep the answer for task 5.
- **Why the third sync wrote nothing.** A page drawn twice is not always the
  same bytes. Why is it here?

## Task 5 — drawing a source that is already held

Add `render: browser` to `uv-projects`.

```bash
dossier sync site-audit
dossier sync site-audit
```

**Checkpoint.** `10 changed`, then `0 fetched`. No `<lastmod>` moved, so why
were ten pages fetched (R1.40 row 8, R2.26)? Before R1.40 row 8, this sync
fetched nothing, and every page stayed held as sent. Task 4 hid that. Why?

Compare the note of `uv-projects/index` with the one you saved in task 2. The
site's theme rewrites every in-page link as an absolute URL when its scripts
run. Then take `render:` away, sync once, and say what that sync fetched and why.
Draw only a site that needs it: in `docs/web-connector.md`, drawing all of uv's
docs took 217 seconds against 12 to 20.

---

## Done when

- you can say why each key and marker has the form it has, and what a second
  sync of a sitemap source asks for;
- you can say what of a page is in its note, what is not, and why nothing was
  chosen by a guess;
- you saw a missing sitemap and a crawl too small fail a listing, named, with
  the next source still synced, and can say why neither lists a part;
- you saw a script-written page held empty, then drawn, and can say what the
  browser was and was not allowed to ask for;
- you can say why adding `render:` to a held source fetches every page once.

## Cleaning up

```bash
rm -rf playground/work/18
```

Chromium stays installed for Playwright; `playwright uninstall` removes it.
Nothing needs cleaning up on any of the three sites, because nothing you ran
could change anything there.

**Back to:** [the playground index](../README.md).
