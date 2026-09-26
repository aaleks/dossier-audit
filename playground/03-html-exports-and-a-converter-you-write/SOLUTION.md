# 03 · Solution

Every block below is marked, as exercises 11 and 15 mark theirs:

| Mark | Means |
|---|---|
| **[run]** | Run against this repository. The output is what it produced. |
| **[derived]** | Worked out from the code or the spec, not printed by a command. |
| **[shape]** | What to expect, and what to check. Not a transcript. |

Nearly everything is **[run]**. The tasks were run in order, in one pass, on
2026-09-26, at the commit of `main` that followed #422, with `dossier` installed
with its `pdf` and `tracking` extras. Task 1's two extra files, task 2's tie and
the test run in "Before you finish" were run again after R8.24 and R8.25 (#435),
which changed what each of them prints. The liberties taken in showing it:

- `dossier` is the repository's CLI, run from `playground/work/03/`, and
  `artifacts.py` is `python ../../03-html-exports-and-a-converter-you-write/resources/artifacts.py`,
  run from the same place.
- Tasks 2 to 5 were run with the solution's package as it stood at each task:
  at `0.1.0` with no image rule until task 5, not opt-in until the end of
  task 2, and without its CSV converter until task 4. `solution/` holds where
  it ends.
- The stub model ran on port 8093 rather than 8099, and logged to a file of its
  own. Where a model is served is in no key (R9.2).
- A run's absolute path is shortened to `…/runs/<id>/`.

Everything here is deterministic apart from run ids and times. Your snapshot
hashes and counts should match these exactly, and so should the artifact hashes
wherever the converter is `dossier`'s or the solution's.

## Run the prepared answer

```bash
# the converter package, installed into the same environment
VIRTUAL_ENV=$PWD/.venv uv pip install --no-deps -e \
  playground/03-html-exports-and-a-converter-you-write/solution/dossier_html_playground

mkdir -p playground/work/03/inbox/postmortems
cp -r playground/03-html-exports-and-a-converter-you-write/solution/workspace/. playground/work/03/
cp playground/corpus/scans/*.pdf \
   playground/corpus/exports/* \
   playground/work/03/inbox/postmortems/

cd playground/work/03
../../../.venv/bin/dossier sync incident-audit
../../../.venv/bin/dossier convert incident-audit
```

**[run]**

```console
postmortems-mixed  0 known · 0 changed · 6 new -> 6 fetched
ledger updated · 6 new snapshots · 0 tombstoned
postmortems-mixed  6 held · 6 converted · 0 cached
cache updated · 6 converted · 0 cached

$ python ../../03-html-exports-and-a-converter-you-write/resources/artifacts.py
PLAY-2001-terminal-scan.pdf               snapshot 89d790a8  pdf-markdown        1.1.0    274 bytes  sha256 d728a34f1c22
PLAY-2002-photocopy-no-text-layer.pdf     snapshot f82d92a3  pdf-markdown        1.1.0     15 bytes  sha256 f4aaa0b27c8b
PLAY-4001-payment-retries.html            snapshot db6997e7  play-html-markdown  0.2.0   1225 bytes  sha256 8a5412c93b1d
PLAY-4002-dns-resolver-flap.html          snapshot 99f12e5e  play-html-markdown  0.2.0   1227 bytes  sha256 0c3c2d0a930c
PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  play-html-markdown  0.2.0     49 bytes  sha256 7c03eb701064
PLAY-4004-incident-register.csv           snapshot 00f25086  text-csv            1.0.0    464 bytes  sha256 00f2508608e2
```

`--no-deps` because this package has none. It is standard library only, and
`--no-deps` keeps `uv` from resolving anything at all. The workspace names
`play-html-markdown` in `sources.yaml`, so the line needs the package: without
it, every command that plans or converts refuses the name.

---

## Task 1 — a mixed folder, and the two ways convert fails

**[run]**

```console
$ dossier sync incident-audit
postmortems-mixed  0 known · 0 changed · 6 new -> 6 fetched
ledger updated · 6 new snapshots · 0 tombstoned

$ dossier convert incident-audit
postmortems-mixed  6 held · 6 converted · 0 cached
cache updated · 6 converted · 0 cached

$ artifacts.py
PLAY-2001-terminal-scan.pdf               snapshot 89d790a8  pdf-markdown        1.1.0    274 bytes  sha256 d728a34f1c22
PLAY-2002-photocopy-no-text-layer.pdf     snapshot f82d92a3  pdf-markdown        1.1.0     15 bytes  sha256 f4aaa0b27c8b
PLAY-4001-payment-retries.html            snapshot db6997e7  html-markdown       1.1.0   1302 bytes  sha256 ec8a656a0b6d
PLAY-4002-dns-resolver-flap.html          snapshot 99f12e5e  html-markdown       1.1.0   1308 bytes  sha256 55f07f33dbcc
PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  html-markdown       1.1.0     50 bytes  sha256 5bfd3d4bcc44
PLAY-4004-incident-register.csv           snapshot 00f25086  text-csv            1.0.0    464 bytes  sha256 00f2508608e2
```

Six documents, three converters, one kind. The `.meta.json` beside each artifact
is what makes that table possible: an artifact without a provenance record is not
a cache entry at all (R0.3), and the record is what gets you from a key back to a
snapshot and a converter. `artifacts.py` reads nothing else.

The register's row is the one to keep. Its artifact's `sha256` is
`00f2508608e2`, and so is its snapshot's: `text-csv` wrote the file back byte for
byte (R8.23 row 1). Task 4 is about why.

The two extra files, and what the folder connector made of them:

**[run]**

```console
$ dossier sync incident-audit
postmortems-mixed  6 known · 0 changed · 2 new -> 8 fetched
ledger updated · 2 new snapshots · 0 tombstoned

$ python -c "import sqlite3; ..."      # key, media_type from the ledger's items
PLAY-4005-connection-pool-exhaustion.html text/html
PLAY-4006-indexer-alerts.json application/json

$ dossier convert incident-audit
postmortems-mixed  8 held · 0 converted · 6 cached · 2 failed
    PLAY-4005-connection-pool-exhaustion.html: ValueError: html-markdown was given bytes that are not valid UTF-8 (invalid start byte at byte 81)
    PLAY-4006-indexer-alerts.json: nothing converts ('application/json', 'markdown'). Claimed pairs: ['(application/pdf, markdown)', '(application/pdf, page_images)', '(application/vnd.dossier.confluence-page+json, markdown)', '(application/vnd.dossier.jira-issue+json, markdown)', '(image/jpeg, page_images)', '(image/png, page_images)', '(text/csv, markdown)', '(text/html, markdown)', '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by installing a package that declares a dossier.converters entry point.
cache updated · 0 converted · 6 cached
$ echo $?
1
```

`.json` is in `MEDIA_TYPES`, so the ledger holds a real media type, and nothing
claims `(application/json, markdown)`. `jira-issue-markdown` and
`confluence-page-markdown` read JSON, but each claims a type of its own
(`application/vnd.dossier.jira-issue+json`, for one), because `application/json` is every
JSON document any source holds (R1.14). That makes this a pair problem, not a
media-type one. Exercise 04's `.log` is the other kind: an extension nobody
recognises at all.

Byte 81 is the en dash in the page's `<title>`. Windows-1252 writes it as the
single byte `0x96`, which cannot begin a character in UTF-8. `html-markdown` decodes UTF-8
itself and never guesses. Handed bytes, BeautifulSoup would guess with whatever
detector the machine has installed, so the same file could convert differently
on two machines (R8.1, R8.21 row 4). The page declares `charset="windows-1252"`,
and that is not read either. Whether it should be is spec 008's open question 6.

Two files, two causes, and one blast radius. The page was read, and one input
was bad. The JSON was never read at all, and it fails alone anyway, because its
pair was `dossier`'s own choice: the source declared no `convert:`, so the kind
came from the default table (R8.10). Nobody asked for anything this installation
cannot make. The file is one somebody dropped in a folder, so it is reported
the way the page is, and the other six are audited (R8.25). The exit is still 1:
an audit that covers less than its source holds must not read as a clean one to
anything checking `$?`.

**[run]** The same folder, with the source declaring the kind every document in
it already had:

```console
$ dossier convert incident-audit        # convert: [markdown]
1 document(s) have no converter:
  PLAY-4006-indexer-alerts.json (application/json): nothing converts ('application/json', 'markdown'). Claimed pairs: ['(application/pdf, markdown)', '(application/pdf, page_images)', '(application/vnd.dossier.confluence-page+json, markdown)', '(application/vnd.dossier.jira-issue+json, markdown)', '(image/jpeg, page_images)', '(image/png, page_images)', '(text/csv, markdown)', '(text/html, markdown)', '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by installing a package that declares a dossier.converters entry point.
$ echo $?
2
```

The Windows-1252 page is not in the message. Neither are the six documents
already converted, although their artifacts are sitting in the cache. A kind
written in `convert:` is a promise the installation has to keep, and one it
cannot keep is known before any work starts. Every document is resolved before
any is converted (`_resolve_converters` in `src/dossier/application/convert.py`),
and one declared pair nothing claims stops all of them (R8.24). Nothing was
read, so nothing about the page's bytes could be known yet.

**[run]**

```console
$ rm inbox/postmortems/PLAY-4006-indexer-alerts.json
$ dossier sync incident-audit
postmortems-mixed  8 known · 0 changed · 0 new -> 7 fetched
      PLAY-4006-indexer-alerts.json  tombstoned
ledger updated · 0 new snapshots · 1 tombstoned

$ dossier convert incident-audit        # convert: [markdown]
postmortems-mixed  7 held · 0 converted · 6 cached · 1 failed
    PLAY-4005-connection-pool-exhaustion.html: ValueError: html-markdown was given bytes that are not valid UTF-8 (invalid start byte at byte 81)
cache updated · 0 converted · 6 cached
$ echo $?
1
```

The six are served from cache. `markdown` was the kind they had by default, so
declaring it chose the same converters, and a convert key is the snapshot, the
converter's id and version, and the options (R5.4). Who chose the kind is not
in it.

The same JSON, the same installation, and one line of `sources.yaml` decided
how far its failure reached. The table in spec 008 is the whole difference:

| What happened | Blast radius | Because |
|---|---|---|
| no converter claims a pair the source declared in `convert:` | the whole run stops | the pipeline asks for something this installation cannot make. Nothing about the run is well-defined, and the fix is an installation or a correction to `convert:`, not a retry (R8.24) |
| a converter fails on one document | that document only | the configuration is right and one input is bad. An audit over nine of ten documents is useful, provided it says which one is missing |

A pair nothing claims for a kind nobody declared is the second row, not the
first. That was the JSON in the first run. Collapsing the two rows one way
turns a pipeline asking for what it cannot have into a list of per-document
errors that look like bad input. The other way turns one corrupt export, or one
stray attachment, into a run that produced nothing. Every message about the
JSON lists every claimed pair, because that turns the error into its own fix.
The stop exits 2 and converts nothing. A document that failed exits 1, and the
line names that one document.

## Task 2 — a converter of your own

`solution/dossier_html_playground/` is a complete package:

```
pyproject.toml
src/dossier_html_playground/__init__.py
src/dossier_html_playground/html_export.py   (text/html, markdown)  play-html-markdown
src/dossier_html_playground/csv_table.py     (text/csv, markdown)   play-csv-table
```

The registration, in `pyproject.toml`:

```toml
dependencies = []

[project.entry-points."dossier.converters"]
play-html-markdown = "dossier_html_playground.html_export:HtmlMarkdownConverter"
play-csv-table = "dossier_html_playground.csv_table:CsvTableConverter"
```

No file under `src/dossier/` changed, and there is no match statement anywhere
(R8.7). `tests/architecture/` has a test that fails if one appears. The
dependency list is empty. `html-markdown` reads HTML with markdownify and
BeautifulSoup, both pinned exactly, because what a library writes is inside the
artifact. This converter is `html.parser` from the standard library, so it pins
nothing, and its version has to cover the interpreter instead (task 5).

What makes it this workspace's converter is one constant:

```python
# What this wiki's exporter wraps around every page, by class. ...
CHROME = frozenset({"breadcrumb"})
```

An element carrying that class is skipped with everything inside it. The parser
counts nesting of the same tag, so a `<div>` inside the breadcrumb does not end
the skip early. It never starts a skip on a void element such as `<img>`, which
has no end tag to close one.

The rest is the contract, and each part is R8.1. It reads no clock, opens no file
other than the bytes it was handed, and asks nothing over the network.
`K_convert` claims an artifact is determined by the snapshot hash, the converter
id, its version and its options. A converter that consulted anything else would
make that key a lie. It decodes UTF-8 strictly, for the reason `html-markdown`
does. And it collapses whitespace inside each block:

```python
# `split()` on no argument collapses every run of whitespace to one space
text = " ".join("".join(self._text).split())
```

An exporter's line wrapping is not information about the document. A page
exported again with different wrapping converts to the same bytes through this
converter, so no step asks about it again (R5.6). `html-markdown` keeps the
wrapping (task 3).

**[run]** Installed, at `0.1.0`, not yet opt-in:

```console
$ python -c "from dossier.infrastructure.converters.registry import installed_converters; ..."
docling-markdown 1.0.0 application/pdf markdown
pdf-markdown 1.1.0 application/pdf markdown
pdf-images 1.0.0 application/pdf page_images
confluence-page-markdown 1.2.0 application/vnd.dossier.confluence-page+json markdown
jira-issue-markdown 1.0.0 application/vnd.dossier.jira-issue+json markdown
jpeg-pages 1.0.0 image/jpeg page_images
png-pages 1.0.0 image/png page_images
text-csv 1.0.0 text/csv markdown
html-markdown 1.1.0 text/html markdown
play-html-markdown 0.1.0 text/html markdown
markdown-text 1.0.0 text/markdown markdown
text-plain 1.0.0 text/plain markdown

$ dossier convert incident-audit
two converters claim the same pair, and picking either would be picking by installation order:
  (text/html, markdown) is claimed by both html-markdown 1.1.0 and play-html-markdown 0.1.0
A workspace settles it by naming one under converters: in sources.yaml (R8.13).
$ echo $?
2
```

Nothing converts, the scans and the register included, and no document is
named. None is at fault: the installation holds two answers for one pair, and
that is refused once, as what it is (R8.24 row 5). `_resolve_converters` in
`src/dossier/application/convert.py` asks `claims` in
`src/dossier/domain/conversion.py` about every installed claim before it
resolves a single document, so a tie anywhere stops the run, however the kinds
were chosen. `claims` refuses rather than choosing, and its docstring says why:
the winner's id and version go into `K_convert`, so settling the tie by
installation order would give two machines with the same packages two different
keys, and every stage key above them would differ too (R5.6).

`docling-markdown` claims `(application/pdf, markdown)` too and caused none of
this, because it is opt-in. An opt-in converter is left out before claims are
counted, unless the workspace names it (`answering`, same file).

The id matters for the same reason. `claims` tells two claims apart by id and
version, and treats the same pair from the same id and version as one claim made
twice. A copy calling itself `html-markdown` at `1.1.0` would be taken for the
shipped converter, and which of the two wrote an artifact would turn on
installation order, under a key saying it made no difference.

**[run]** Settled by the workspace, misspelt once:

```console
$ dossier convert incident-audit        # converters: [play-html-markdwn]
sources.yaml names play-html-markdwn under converters:, and no installed package provides it. Installed: confluence-page-markdown, docling-markdown, html-markdown, jira-issue-markdown, jpeg-pages, markdown-text, pdf-images, pdf-markdown, play-html-markdown, png-pages, text-csv, text-plain. A converter is added by installing a package that declares a dossier.converters entry point.
$ echo $?
2

$ dossier convert incident-audit        # converters: [play-html-markdown]
postmortems-mixed  6 held · 3 converted · 3 cached
cache updated · 3 converted · 3 cached

$ dossier convert incident-audit
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached
```

Three exports converted under a key that names `play-html-markdown`. The scans
and the register are cached, because their converters, and so their keys, did not
change. The choice sits in `sources.yaml`, beside `sources:`, because a manifest
pins one converter per pair (R8.9) and a replay recomposes every conversion from
that pin (R4.7). One converter per pair per workspace keeps both true.

**[run]** With `opt_in = True` added to the class:

```console
$ dossier convert incident-audit        # converters: [play-html-markdown]
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached

$ dossier convert incident-audit        # no converters: line
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached
```

Neither refuses. Named, `play-html-markdown` answers, from the artifacts it just
made. Unnamed, `html-markdown` answers, from the artifacts it made in task 1.

**Should it be opt-in?** Yes, and the solution's converters both are. Opt-in
saved every other workspace on the machine, and the repository's test suite,
from a refusal over a converter they never asked for (see "Before you finish").
What it costs: someone who installs the package and expects it to answer gets
`html-markdown` instead, silently, until they name it. Nothing warns that an
installed converter is being passed over. For a converter whose whole reason is
one workspace's exporter, that is the right way round. A converter meant to
replace the shipped one everywhere would be a different argument, and a spec
amendment rather than a package.

## Task 3 — what a stage would actually see

**[run]**

```console
$ artifacts.py PLAY-4001 --cat
PLAY-4001-payment-retries.html            snapshot db6997e7  html-markdown       1.1.0   1302 bytes  sha256 ec8a656a0b6d
  .dossier/cache/convert/b6/c1/b6c18f49610620574ae9e45d54cd6f259ca3a165c46ab0b72f9fa3f0bc0bacf2
    Spaces / Site Reliability / Postmortems / 2026 / PLAY-4001

    # PLAY-4001 — Duplicate payment retries after a queue redelivery

    **Severity:** major
    **Resolved:** 2026-04-18
    **Systems affected:** payments-worker, orders-api

    ## Timeline

    - 2026-04-17 21:06 UTC — the payments worker is restarted during a routine
      node drain while 1,900 messages are in flight.
    …

PLAY-4001-payment-retries.html            snapshot db6997e7  play-html-markdown  0.1.0   1225 bytes  sha256 8a5412c93b1d
  .dossier/cache/convert/59/da/59da064a2b35addcb478b1cbc34b752747e0a007435c2df7f5537d3d4446c073
    # PLAY-4001 — Duplicate payment retries after a queue redelivery

    Severity: major

    Resolved: 2026-04-18

    Systems affected: payments-worker, orders-api

    ## Timeline

    - 2026-04-17 21:06 UTC — the payments worker is restarted during a routine node drain while 1,900 messages are in flight.
    …
```

Both artifacts are in the cache. Naming a converter deleted nothing, because the
cache is addressed by the key of the computation that made an entry.

Three differences, and only the first was the point:

- **The breadcrumb** is gone from yours.
- **The bold labels.** `html-markdown` writes `**Severity:** major`, and yours
  writes `Severity: major`. A span quoted from either is found in the other,
  because the span check folds the markdown a converter wrote around words
  (R6.20).
- **The wrapping.** `html-markdown` keeps the exporter's line breaks inside a
  paragraph, and yours joins them. A span that crosses a line break is still
  found, because the check collapses whitespace on both sides. What differs is
  the hash: re-wrap the export and `html-markdown`'s note changes, while yours
  does not.

**[run]**

```console
$ artifacts.py PLAY-4003 --cat
PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  html-markdown       1.1.0     50 bytes  sha256 5bfd3d4bcc44
  .dossier/cache/convert/54/d4/54d4637de69c3239520778e93cbc111c9d7a0c2c4707b5968b1e827079dac159
    ![panel-checkout-p99.png](panel-checkout-p99.png)

PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  play-html-markdown  0.1.0      0 bytes  sha256 e3b0c44298fc
  .dossier/cache/convert/2b/e1/2be1c9d44496c796ff0487e32f2f628122954d6547663df2ce78b7b601900db3
    (nothing)

$ artifacts.py PLAY-2002 --cat
PLAY-2002-photocopy-no-text-layer.pdf     snapshot f82d92a3  pdf-markdown        1.1.0     15 bytes  sha256 f4aaa0b27c8b
  .dossier/cache/convert/6f/c9/6fc9997cf483a96973a49b9918896af26e821b1ac827991a6e43618d18cb67ec
    <!-- page 1 -->
```

`e3b0c44298fc` is the start of the SHA-256 of nothing at all. Yours converted
`PLAY-4003` to zero bytes. The page is a Grafana panel shared as one `<img>`, a
`<style>` and a `<script>`, and none of that is text a person wrote.

**Should the converter have failed instead?** No. The bytes are a valid page
that carries no sentence, and raising would report the *document* as broken when
the expectation was wrong. `pdf-markdown` reached the same conclusion for the
photocopy: it introduced the page by its anchor, which is what makes
`source.page` a fact derived from the document rather than a number a model
asserted (R6.14), and then had nothing to put under it.

**Should it have written nothing?** That is where the shipped converter
disagrees with yours, and the question to settle it is whether a step runs for an
empty note. It does. `_reads_nothing` in `src/dossier/application/run.py` asks
whether a document holds an artifact *of the kind the step reads*, not whether
the artifact holds anything. R6.21 skips a PNG for a step reading `markdown`,
because the PNG has no `markdown` artifact at all. An empty `markdown` artifact
is still one. So with `0.1.0` named, a model is asked about a document with
nothing in it. The optional stub run below makes that call. Its log records each
prompt's length, and `PLAY-4003`'s is the shortest of the six, at 400
characters: 13 fewer than the photocopy's, whose note is only its page anchor.

**[derived]** So the answer the solution reaches is the third one. Write what the
page states about its picture: its alt text, and failing that the name of its
file, and never a URL or a `data:` URI (R8.22). That is not made-up text. The
file's name is on the page, and the model sees a note that says, truthfully, that
this document is a picture called `panel-checkout-p99.png` and nothing else.
Task 5 is that change.

The move:

**[run]**

```console
$ sed -i 's#Spaces / Site Reliability / Postmortems#Spaces / Payments / Postmortems#' \
    inbox/postmortems/PLAY-4001-payment-retries.html
$ dossier sync incident-audit
postmortems-mixed  6 known · 1 changed · 0 new -> 6 fetched
      PLAY-4001-payment-retries.html  db6997e7472c386585ceb5f9de70941af59525cbef2b310519c03eeffa513d9e -> b16b34b4945f7d4757241b012ead41a3b6afe32ac54a9247891276f801102513
ledger updated · 1 new snapshots · 0 tombstoned

$ dossier convert incident-audit
postmortems-mixed  6 held · 1 converted · 5 cached
cache updated · 1 converted · 5 cached

$ artifacts.py PLAY-4001
PLAY-4001-payment-retries.html            snapshot db6997e7  html-markdown       1.1.0   1302 bytes  sha256 ec8a656a0b6d
PLAY-4001-payment-retries.html            snapshot b16b34b4  play-html-markdown  0.1.0   1225 bytes  sha256 8a5412c93b1d
PLAY-4001-payment-retries.html            snapshot db6997e7  play-html-markdown  0.1.0   1225 bytes  sha256 8a5412c93b1d

$ dossier convert incident-audit        # no converters: line
postmortems-mixed  6 held · 1 converted · 5 cached
cache updated · 1 converted · 5 cached

$ artifacts.py PLAY-4001
PLAY-4001-payment-retries.html            snapshot b16b34b4  html-markdown       1.1.0   1294 bytes  sha256 d84843e2bdbc
PLAY-4001-payment-retries.html            snapshot db6997e7  html-markdown       1.1.0   1302 bytes  sha256 ec8a656a0b6d
PLAY-4001-payment-retries.html            snapshot b16b34b4  play-html-markdown  0.1.0   1225 bytes  sha256 8a5412c93b1d
PLAY-4001-payment-retries.html            snapshot db6997e7  play-html-markdown  0.1.0   1225 bytes  sha256 8a5412c93b1d
```

One snapshot changed, so one document converted under a new key, as it must: the
key is over the snapshot. Your converter wrote the same 1225 bytes for it.
`html-markdown` wrote 1294 new ones. `K_stage` covers the hashes of the inputs a
step reads, not the snapshot behind them (spec 005). So a step over your note is
served from cache, and a step over `html-markdown`'s asks the model again. Across
a wiki reorganisation that moves four hundred pages, that is the difference
between no calls and four hundred.

**[run]** The optional check, with `converters: [play-html-markdown]` back in
place and the stub answering from `resources/replies.json`:

```console
$ dossier run incident-audit
run 20260926T101423Z-e10d · …/runs/20260926T101423Z-e10d/manifest.json
  extract: 6 document(s) · 0 from cache · 0 failed · tokens not reported
$ wc -l < /tmp/dossier-calls-03.jsonl
6

$ sed -i 's#Spaces / Payments / Postmortems#Spaces / Finance / Postmortems#' \
    inbox/postmortems/PLAY-4001-payment-retries.html
$ dossier sync incident-audit
postmortems-mixed  6 known · 1 changed · 0 new -> 6 fetched
      PLAY-4001-payment-retries.html  b16b34b4945f7d4757241b012ead41a3b6afe32ac54a9247891276f801102513 -> 7e557d1c7d5fc17ce83d63aa1f1e4514536f2cb450697bf2612d7b666ae0d97b
ledger updated · 1 new snapshots · 0 tombstoned

$ dossier run incident-audit
warning: the source has moved since run 20260926T101423Z-e10d: PLAY-4001-payment-retries.html re-snapshotted
run 20260926T101425Z-ab68 · …/runs/20260926T101425Z-ab68/manifest.json
  extract: 6 document(s) · 6 from cache · 0 failed
$ wc -l < /tmp/dossier-calls-03.jsonl
6
```

The run warns that the source moved, which is true, and asks nothing, which is
the point. The first run's six calls include `PLAY-4003`, asked about an empty
note.

**What did leaving the breadcrumb out cost?** The note no longer says which space
a postmortem lives in, so a question like "which team's postmortems cite a
retry storm" cannot be answered from the notes. The decision is also a fact
about one exporter. Point this converter at a wiki that writes its trail as
`<nav>`, and the trail is kept, silently. That is exactly the heuristic spec 008
declined to make for every workspace, made here for one.

## Task 4 — a register as a table

**[run]** The second converter, opt-in from the start, installed and then named:

```console
$ uv pip install --no-deps -e …/dossier_html_playground      # the new entry point
$ python -c "…installed_converters…"
…
text-csv 1.0.0 text/csv markdown
play-csv-table 0.1.0 text/csv markdown
html-markdown 1.1.0 text/html markdown
play-html-markdown 0.1.0 text/html markdown
…

$ dossier convert incident-audit        # converters: [play-html-markdown]
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached

$ dossier convert incident-audit        # converters: [play-html-markdown, play-csv-table]
postmortems-mixed  6 held · 1 converted · 5 cached
cache updated · 1 converted · 5 cached

$ artifacts.py PLAY-4004 --cat
PLAY-4004-incident-register.csv           snapshot 00f25086  play-csv-table      0.1.0    571 bytes  sha256 9ea6235dc1c7
  .dossier/cache/convert/da/71/da71399bb2f95d34a5107a72a8a63d721f6233028613d8e73346445f20174aea
    | key | opened | severity | system | root_cause | recorded_loss_chf |
    | --- | --- | --- | --- | --- | --- |
    | PLAY-4001 | 2026-04-17 | major | payments-worker | redelivered messages charged twice with no idempotency key | 1240 |
    | PLAY-4002 | 2026-05-08 | minor | internal-dns | one resolver replica running an eight-month-old image | 0 |
    | PLAY-4005 | 2026-06-21 | major | orders-api | connection pool exhausted by a report query holding transactions open | 9800 |
    | PLAY-4006 | 2026-07-02 | minor | search-indexer | indexer restarted mid-batch and skipped a shard | 0 |

PLAY-4004-incident-register.csv           snapshot 00f25086  text-csv            1.0.0    464 bytes  sha256 00f2508608e2
  …
```

Installing it changed nothing, because it is opt-in. Named, it converted exactly
one document. `play-csv-table` shares `markdown` with `play-html-markdown` and
collides with nothing of its own, because a pair is two halves and only the media
type moved.

**[run]** The argument, tested:

```console
$ python - <<'PY'
from pathlib import Path

from dossier.domain.grounding import locate_span
from dossier.infrastructure.converters.registry import installed_converters

by_id = {c.id: c for c in installed_converters()}
csv_bytes = Path("inbox/postmortems/PLAY-4004-incident-register.csv").read_bytes()
table = by_id["play-csv-table"].convert(csv_bytes, {}).decode()
text = by_id["text-csv"].convert(csv_bytes, {}).decode()

spans = {
    "one cell": "connection pool exhausted by a report query holding transactions open",
    "a row, as the table shows it": "| PLAY-4005 | 2026-06-21 | major | orders-api |",
    "a row, as the file has it": "PLAY-4005,2026-06-21,major,orders-api",
}
print(f"{'':32} {'in the table':>13} {'in the file':>12}")
for name, span in spans.items():
    print(
        f"{name:32} {locate_span(span, document_text=table)!s:>13} "
        f"{locate_span(span, document_text=text)!s:>12}"
    )

piped = b"key,root_cause\nPLAY-4007,retries | no backoff\n"
piped_table = by_id["play-csv-table"].convert(piped, {}).decode()
print()
print(piped_table)
span = "retries | no backoff"
print(f"{span!r} in the table: {locate_span(span, document_text=piped_table)}")
print(f"{span!r} in the file:  {locate_span(span, document_text=piped.decode())}")
PY
                                  in the table  in the file
one cell                                  True         True
a row, as the table shows it              True        False
a row, as the file has it                False         True

| key | root_cause |
| --- | --- |
| PLAY-4007 | retries \| no backoff |
'retries | no backoff' in the table: False
'retries | no backoff' in the file:  True
```

A single cell grounds either way. That is most of what a model quotes, and it is
why a table looks harmless. The rows show what grounding actually promises. A
span is grounded when it occurs in the text the step was shown (R6.4). With a
table, that text is something this converter wrote, so a row quoted from it is
"grounded" and cannot be found in the register. A reviewer who opens the CSV to
check the evidence finds nothing. With `text-csv` the note *is* the file, so
grounded in one means found in the other.

The pipe is worse, because it fails inside `dossier`'s own check. The table has to
escape `|` or the cell splits in two, and the backslash is a character the
register does not hold. A model that quotes the cell the way a person reads it has
quoted a span the note does not contain. The field is ungrounded, and scored
incorrect however right its value is (R7.4). The note is also 571 bytes where the
file is 464.

**[run]** So the solution leaves it installed and unnamed:

```console
$ dossier convert incident-audit        # converters: [play-html-markdown]
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached
```

`text-csv`'s artifact from task 1 is still in the cache, so nothing converts.

**Could you have claimed `(text/html, page_images)` and rendered the page
instead?** You can register the pair. What you cannot do is decide what a step
receives for it. `PART_TYPE` in `src/dossier/domain/conversion.py` is
`image/png`, and every part of a non-`markdown` kind is labelled with it as it is
unpacked. A step reading `documents@page_images` sends your parts to the model as
PNGs, and a container that is not `pack_parts` output raises before it gets there
(R8.11). A kind is not a free-form label. It is a contract about what the bytes
are, agreed in a spec. Exercise 10 is that contract being used.

## Task 5 — the promise a version makes

**[run]** The image rule added, and `0.1.0` raised to `0.2.0`:

```console
$ dossier convert incident-audit
postmortems-mixed  6 held · 3 converted · 3 cached
cache updated · 3 converted · 3 cached

$ artifacts.py play-html-markdown
PLAY-4001-payment-retries.html            snapshot 7e557d1c  play-html-markdown  0.1.0   1225 bytes  sha256 8a5412c93b1d
PLAY-4001-payment-retries.html            snapshot b16b34b4  play-html-markdown  0.1.0   1225 bytes  sha256 8a5412c93b1d
PLAY-4001-payment-retries.html            snapshot db6997e7  play-html-markdown  0.1.0   1225 bytes  sha256 8a5412c93b1d
PLAY-4001-payment-retries.html            snapshot 7e557d1c  play-html-markdown  0.2.0   1225 bytes  sha256 8a5412c93b1d
PLAY-4002-dns-resolver-flap.html          snapshot 99f12e5e  play-html-markdown  0.1.0   1227 bytes  sha256 0c3c2d0a930c
PLAY-4002-dns-resolver-flap.html          snapshot 99f12e5e  play-html-markdown  0.2.0   1227 bytes  sha256 0c3c2d0a930c
PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  play-html-markdown  0.1.0      0 bytes  sha256 e3b0c44298fc
PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  play-html-markdown  0.2.0     49 bytes  sha256 7c03eb701064
```

Exactly three converted: the three `play-html-markdown` produced. `pdf-markdown`
and `text-csv` did not move, so their three were served from cache. (`PLAY-4001`
has three `0.1.0` rows because the page moved twice, once in task 3's optional
check. Without it you will see two.) A version
invalidates every artifact that converter produced and nothing else (R5.4). Two
of the three came back byte for byte, because neither page has an image. Only
`PLAY-4003`'s note changed, and a step's key is over the note, so a run after the
bump asks about one document rather than three. The run at the end of this task
shows it.

**[run]** The version put back to `0.1.0`, the new code kept:

```console
$ dossier convert incident-audit
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached

$ artifacts.py PLAY-4003 --cat
PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  html-markdown       1.1.0     50 bytes  sha256 5bfd3d4bcc44
  .dossier/cache/convert/54/d4/54d4637de69c3239520778e93cbc111c9d7a0c2c4707b5968b1e827079dac159
    ![panel-checkout-p99.png](panel-checkout-p99.png)

PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  play-html-markdown  0.1.0      0 bytes  sha256 e3b0c44298fc
  .dossier/cache/convert/2b/e1/2be1c9d44496c796ff0487e32f2f628122954d6547663df2ce78b7b601900db3
    (nothing)

PLAY-4003-latency-dashboard-export.html   snapshot 614caa61  play-html-markdown  0.2.0     49 bytes  sha256 7c03eb701064
  .dossier/cache/convert/61/24/612447887b4084b2c598f886ea456bef07adacf694e5b76c0a4c763b7f7a2f1a
    ![panel-checkout-p99.png](panel-checkout-p99.png)
```

Nothing converted, and a step reading `PLAY-4003` now gets the empty note. The
code installed would write 49 bytes for that page, and the cache served zero,
under a key that says `play-html-markdown 0.1.0` made them. That was true once.
Nothing reported it and nothing could: the only evidence is the code itself, and
no key covers code, only the version its author declared.

**[run]** `0.2.0` again:

```console
$ dossier convert incident-audit
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached
```

Nothing converted, because the `0.2.0` artifacts were never deleted. Two versions
of one converter sit side by side in the cache, which is what makes going back
cheap.

**[run]** With the stub from task 3's optional check started again, on a fresh
call log. The last run before this one was task 3's, at `0.1.0`:

```console
$ dossier run incident-audit
run 20260926T101947Z-5b63 · …/runs/20260926T101947Z-5b63/manifest.json
  extract: 6 document(s) · 5 from cache · 0 failed · tokens not reported
$ wc -l < /tmp/dossier-calls-03.jsonl
1
```

One call, for `PLAY-4003`, which now reads as the name of its picture. The other
two exports were converted again under `0.2.0` and served from the step's cache,
because their notes did not change.

**Is a change to `CHROME` a version bump?** Yes. It decides what text reaches the
artifact, and the obligation is on output, not on how large the edit felt.

**Is a new `html.parser` a version bump?** The same answer, and an uncomfortable
one. Your converter's behaviour includes everything it calls, and here that is
the interpreter you happen to run. `html-markdown` pins markdownify and
beautifulsoup4 exactly for this reason, and the comment on its version says it is
raised when "the pin on markdownify or beautifulsoup4 moves". A standard-library
parser is a defensible thing not to pin. Pretending it cannot change the artifact
is not.

---

## Before you finish

**[run]** Two names for one pair:

```console
$ dossier convert incident-audit        # converters: [play-html-markdown, html-markdown]
sources.yaml names two converters for one pair under converters:, and either would be picking by the order the list was written in:
  (text/html, markdown) is claimed by both html-markdown and play-html-markdown
$ echo $?
2
```

R8.13 row 5. A list in YAML has an order, and deciding by it would make the
converter a fact about how someone typed a line rather than a decision anyone
made.

**[run]** The suite, with the solution's package installed and both converters
opt-in:

```console
$ pytest -q
…
$ echo $?
0

$ pytest -o addopts="" -rA tests/unit/test_R008_1__conversion_is_a_pure_function_of_its_input.py | grep play-
PASSED …::TestEveryConverterIsPure::test_converting_twice_produces_identical_bytes[play-csv-table-0.1.0]
PASSED …::TestEveryConverterIsPure::test_converting_twice_produces_identical_bytes[play-html-markdown-0.2.0]
PASSED …::TestEveryConverterIsPure::test_two_processes_with_different_environments_agree[play-csv-table-0.1.0]
PASSED …::TestEveryConverterIsPure::test_two_processes_with_different_environments_agree[play-html-markdown-0.2.0]
PASSED …::TestEveryConverterIsPure::test_the_artifact_is_not_the_input_object[play-csv-table-0.1.0]
PASSED …::TestEveryConverterIsPure::test_the_artifact_is_not_the_input_object[play-html-markdown-0.2.0]
PASSED …::TestEveryConverterIsPure::test_declaring_an_option_produces_its_own_artifact[play-csv-table-0.1.0]
PASSED …::TestEveryConverterIsPure::test_declaring_an_option_produces_its_own_artifact[play-html-markdown-0.2.0]
```

Green, and not because the suite ignored the package. The R8.1 rows are a
conformance check over every installed converter whose media type the file has a
sample payload for. `text/html` and `text/csv` both have one since `html-markdown`
and `text-csv` shipped, so both of yours were converted twice in one process, and
once each in two processes with different `PYTHONHASHSEED`, `LC_ALL`, `TZ` and
working directory, and gave the same bytes every time. A converter that read the
clock or the locale would fail here, in someone else's test suite, the day it was
installed.

**[run]** Then with `opt_in` taken off `play-html-markdown`:

```console
$ pytest -q tests/acceptance
EEEEEEEEEEEEE.................................F...FFFFFFFFFFF..FEEEE..F. [ 17%]
…
$ echo $?
1
```

158 failures and 136 errors, in 77 of the 95 acceptance files. Nearly all of them
are a `convert` or a `run` exiting 2 where the test expected 0, and the output
behind that is one refusal. The rest are what follows from it: a model asked
nothing, a tracker that saw no run.

```
two converters claim the same pair, and picking either would be picking by installation order:
  (text/html, markdown) is claimed by both html-markdown 1.1.0 and play-html-markdown 0.2.0
A workspace settles it by naming one under converters: in sources.yaml (R8.13).
```

It names no document, and most of those tests never see an HTML file: their
workspaces hold markdown notes such as `INC-4821`. They fail because a tie among
installed claims is refused before any document is looked at, and none of the
workspaces the suite builds names either converter. The suite is right: what a run reads depends on the
environment it ran in, and a test that shrugged at a tie would let a machine's
installation order decide keys. The package is right too, once it is opt-in.
What was wrong was where it was installed.

```bash
VIRTUAL_ENV=$PWD/.venv uv pip uninstall dossier-html-playground
```

Then take the `converters:` line out of `playground/work/03/sources.yaml`, or
every command there refuses the name. A converter is a workspace's dependency. It
has no business in the environment that tests the repository, opt-in or not.

---

## What to take to your own project

- Register capability, do not branch on it. A new format is a package somebody
  installs, never a case in a match statement in the core.
- Separate "we cannot read this kind of thing" from "we could not read this
  thing". They want different fixes and deserve different blast radii. Then
  ask who wanted it read: a pipeline that asked for what it cannot have is
  misconfigured, and a stray file nobody asked about is one missing document.
- When two things can answer, make the choice something a person writes down,
  where it is read once and pinned. Refuse the tie rather than settle it by
  installation order, and let a newcomer arrive opt-in so that installing it
  decides nothing.
- A general tool should not guess what is chrome. A workspace that knows its
  source can decide, and should say in its converter that it did.
- "Grounded" is only as good as the relation between the note and the document.
  A converter that rewrites text moves the evidence somewhere nobody will look.
- A converter version is a cache invalidation key wearing a semver hat. Treat a
  dependency bump, including the standard library's, as a behaviour change unless
  you can show it is not.
- Look at the converted text before you spend a model call on it.
