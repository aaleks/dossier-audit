# 03 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

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

`--no-deps` because this package has none — it is standard library only, and
`--no-deps` keeps `uv` from resolving anything at all, which keeps the install
offline.

---

## Task 1 — the refusal

```console
$ dossier sync incident-audit
postmortems-mixed  0 known · 0 changed · 6 new -> 6 fetched
ledger updated · 6 new snapshots · 0 tombstoned

$ dossier convert incident-audit
4 document(s) have no converter:
  PLAY-4001-payment-retries.html (text/html): nothing converts ('text/html', 'markdown').
  Claimed pairs: ['(application/pdf, markdown)', '(application/pdf, page_images)',
  '(image/jpeg, page_images)', '(image/png, page_images)', '(text/markdown, markdown)',
  '(text/plain, markdown)']. A converter is added by installing a package that declares a
  dossier.converters entry point.
  PLAY-4002-dns-resolver-flap.html (text/html): …
  PLAY-4003-latency-dashboard-export.html (text/html): …
  PLAY-4004-incident-register.csv (text/csv): …
exit 2
```

Sync did not care. It fetched bytes, hashed them, recorded a media type from the
extension table and wrote six snapshots — everything it promises to do, with no
opinion about what any of them contains.

Convert did care, and stopped **everything**, including the two scans that are
claimed twice over and would have converted without complaint:

| What happened | Blast radius | Because |
|---|---|---|
| no converter claims a pair | the whole run stops | the pipeline is not configured to read what it was pointed at. Nothing about the run is well-defined, and the fix is an installation, not a retry |
| a converter fails on one document | that document only | the configuration is right and one input is bad. An audit over nine of ten documents is useful, provided it says which one is missing |

Collapsing those one way turns an installation problem into nine mysterious
per-document errors; the other way turns one corrupt export into a run that
produced nothing. The message lists the claimed pairs because that turns the
error into its own fix: you can see immediately that `markdown` is claimed for
four media types and that nothing has claimed `text/html` at all.

Two details in that list are worth a second look.

- **Both PDF pairs are there**, from `dossier[pdf]`. The format that used to be
  this exercise's subject now ships — through the entry-point group you are about
  to use, behind an extra, with no special case anywhere in the core (R8.7
  counter-example 3). `src/dossier/infrastructure/converters/pdf_markdown.py` is
  the reference implementation for what you are writing.
- **`image/png` resolves to `page_images`, not to `markdown`.** That is R8.10,
  and it is exercise 04.

## Task 2 — the converter

`solution/dossier_html_playground/` is a complete package:

```
pyproject.toml
src/dossier_html_playground/__init__.py
src/dossier_html_playground/html_export.py   (text/html, markdown)
src/dossier_html_playground/csv_table.py     (text/csv, markdown)
```

The registration, in `pyproject.toml`:

```toml
[project.entry-points."dossier.converters"]
html-markdown = "dossier_html_playground.html_export:HtmlMarkdownConverter"
csv-markdown = "dossier_html_playground.csv_table:CsvMarkdownConverter"

dependencies = []
```

Note what is *not* here: no edit to any file under `src/dossier/`, and no match
statement anywhere (R8.7, and `tests/architecture/` has a test that fails if one
appears). And note that the dependency list is empty. The entry-point mechanism
is usually argued for with a large dependency — `dossier`'s own PDF pair is
behind an extra precisely because PDFium has its own release cadence — but it
costs nothing when the converter is forty lines of `html.parser`, and a mechanism
you only reach for when it hurts is a mechanism nobody learns.

The converter's contract, in the three things it does not do, each of them R8.1:
it reads no clock, it opens no file other than the bytes it was handed, and it
asks nothing over the network. `K_convert` claims an artifact is determined by
the snapshot hash, the converter id, its version and its options. If a converter
consults anything else, the key is a lie — the cache serves text that no longer
matches what the converter would produce today, nothing detects it, and every
stage above inherits the error with a provenance record that looks correct.

There is a fourth thing in this one, and it is the interesting one:

```python
# `split()` on no argument collapses every run of whitespace to one space
text = " ".join("".join(self._text).split())
```

An exporter's indentation is not information about the document. Two exports of
the same wiki page with different wrapping must hash the same, or a cosmetic
change to a template invalidates a whole corpus (R5.6). The same reasoning is why
`csv_table.py` refuses to use `csv.Sniffer`: sniffing makes the artifact a
function of how much of the file the sniffer happened to look at, so a register
would convert one way today and another way after a row was appended — under the
same key.

`options` is accepted and unused. Taking the argument keeps every converter
called the same way, and options are part of the key, so an option nobody reads
still produces its own cache entry rather than quietly sharing one.

With the HTML converter installed and the CSV one not yet written:

```console
$ dossier convert incident-audit
1 document(s) have no converter:
  PLAY-4004-incident-register.csv (text/csv): nothing converts ('text/csv', 'markdown').
  Claimed pairs: ['(application/pdf, markdown)', '(application/pdf, page_images)',
  '(image/jpeg, page_images)', '(image/png, page_images)', '(text/html, markdown)',
  '(text/markdown, markdown)', '(text/plain, markdown)']. A converter is added by
  installing a package that declares a dossier.converters entry point.
exit 2
```

Three exports left the list and `(text/html, markdown)` joined the claimed pairs
— and the run still produced nothing at all, over one CSV. Every document is
resolved before any is converted (`_resolve_converters` in
`src/dossier/application/convert.py`), which is what makes R8.5 a property of the
*run* rather than a per-document error that happens to be common.

## Task 3 — what a stage would actually see

```console
$ python - <<'PY'
import json, pathlib, sqlite3
names = dict(sqlite3.connect(".dossier/ledger.db").execute("select content_hash, key from items"))
for meta in sorted(pathlib.Path(".dossier/cache/convert").rglob("*.meta.json")):
    m = json.loads(meta.read_text(encoding="utf-8"))
    art = meta.parent / meta.name[: -len(".meta.json")]
    print(f"{names[m['snapshot']]:42} {m['converter_id']:14} {art.stat().st_size:>6} bytes")
PY
PLAY-4002-dns-resolver-flap.html           html-markdown    1287 bytes
PLAY-4001-payment-retries.html             html-markdown    1285 bytes
PLAY-4003-latency-dashboard-export.html    html-markdown       0 bytes
PLAY-2002-photocopy-no-text-layer.pdf      pdf-markdown       15 bytes
PLAY-4004-incident-register.csv            csv-markdown      571 bytes
PLAY-2001-terminal-scan.pdf                pdf-markdown      274 bytes
```

The mapping is the point of the `.meta.json` beside each artifact: an artifact
without a provenance record is not a cache entry at all (R0.3), and the record is
what lets you go from a key back to a snapshot and a converter.

`PLAY-4001` reads back as text a stage can ground a span in:

```console
$ head -c 220 .dossier/cache/convert/23/bb/23bb8cfa2f65…
Spaces / Site Reliability / Postmortems / 2026 / PLAY-4001

# PLAY-4001 — Duplicate payment retries after a queue redelivery

Severity: major

Resolved: 2026-04-18

Systems affected: payments-worker, orders-api
```

`PLAY-4003` reads back as nothing at all:

```console
$ wc -c < .dossier/cache/convert/2e/ef/2eef475618db…
0
```

Zero bytes. That export is a Grafana panel shared as a page whose body is one
`<img>`, a `<style>` block and a `<script>` — and none of that is text a person
wrote.

The photocopy is fifteen of them, and nobody in this exercise wrote the converter
that produced it:

```console
$ cat .dossier/cache/convert/6f/c9/6fc9997cf483…
<!-- page 1 -->
```

`pdf-markdown` reads a PDF's text layer, and that scan has none. It did not fail
either — it introduced the page by its anchor, which is what makes `source.page` a
fact derived from the document rather than a number the model asserted (R6.14),
and then had nothing to put under it. Two formats, two converters written by two
people, the same answer: the document converted, and what it contains is the
finding.

**Should the converter have failed instead?** No — and the reasoning is worth
keeping:

- The bytes genuinely carry no text. Raising an error would report the *document*
  as broken when the document is fine and the expectation was wrong.
- An empty artifact is visible here, cheaply, before a single model call. That is
  what `dossier convert` is for, and it is exactly why the command exists as
  something you can run early even though `run` converts anyway.
- If such a document reaches a stage, the failure is honest and specific: the
  model has nothing to cite, so any value it returns is ungrounded and is scored
  incorrect (R6.4, R7.4). Exercise 06 shows that outcome directly.

What the *pipeline* should do about a page with no text — render it and look at
it, exclude it, or fail the run — is a question for whoever owns the corpus.
Note that `dossier` has since answered exactly this question for images, in
exactly the form this repository accepts: a spec amendment, R8.10 and R8.11,
then the code. Exercise 10 is the result.

## Task 4 — a second pair from the same package

```console
$ python -c "
from dossier.infrastructure.converters.registry import installed_converters
for c in installed_converters(): print(c.id, c.version, c.media_type, c.kind)"
pdf-markdown 1.1.0 application/pdf markdown
pdf-images 1.0.0 application/pdf page_images
jpeg-pages 1.0.0 image/jpeg page_images
png-pages 1.0.0 image/png page_images
csv-markdown 0.1.0 text/csv markdown
html-markdown 0.1.0 text/html markdown
markdown-text 1.0.0 text/markdown markdown
text-plain 1.0.0 text/plain markdown

$ dossier convert incident-audit
postmortems-mixed  6 held · 6 converted · 0 cached
cache updated · 6 converted · 0 cached

$ dossier convert incident-audit
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached
```

Eight converters, three of them used, one kind between them. `csv-markdown`
shares `markdown` with `html-markdown`, `markdown-text`, `text-plain` and
`pdf-markdown` and collides with none of them, because the pair is two halves and
only the media type moved. The register reads back as a table:

```console
$ cat .dossier/cache/convert/76/5c/765cceb5e566…
| key | opened | severity | system | root_cause | recorded_loss_chf |
| --- | --- | --- | --- | --- | --- |
| PLAY-4001 | 2026-04-17 | major | payments-worker | redelivered messages charged twice with no idempotency key | 1240 |
| PLAY-4002 | 2026-05-08 | minor | internal-dns | one resolver replica running an eight-month-old image | 0 |
| PLAY-4005 | 2026-06-21 | major | orders-api | connection pool exhausted by a report query holding transactions open | 9800 |
| PLAY-4006 | 2026-07-02 | minor | search-indexer | indexer restarted mid-batch and skipped a shard | 0 |
```

**Could you have claimed `(text/html, page_images)` and rendered the page
instead?** You can register the pair; what you cannot do is decide what a step
receives for it. `PART_TYPE` in `src/dossier/domain/conversion.py` is
`image/png`, and the composition root labels every part of a non-`markdown` kind
with it as it unpacks — so a step reading `documents@page_images` sends your
parts to the model as PNGs, and a container that is not `pack_parts` output
raises before it gets there (R8.11). A kind is not a free-form label: it is a
contract about what the bytes are, agreed in a spec. Exercise 10 is that contract
being used.

## Task 5 — the promise a version makes

```console
$ # version = "0.2.0" in html_export.py
$ dossier convert incident-audit
postmortems-mixed  6 held · 3 converted · 3 cached
cache updated · 3 converted · 3 cached

$ # version back to "0.1.0"
$ dossier convert incident-audit
postmortems-mixed  6 held · 0 converted · 6 cached
cache updated · 0 converted · 6 cached
```

Exactly three re-converted: the three `html-markdown` produced. `csv-markdown`
and `pdf-markdown` did not move, so their three artifacts were served from cache — a
version invalidates "every artifact that converter produced and nothing else"
(R5.4).

Reverting the version served the *original* entries again, because nothing was
deleted. The cache is addressed by the key of the computation that made an entry,
not by content, so two versions of one converter coexist happily.

**Is a change to `DROPPED` a version bump?** Yes. It decides what text reaches
the artifact, and the obligation is on output, not on how large the edit felt.

**Is a change to `html.parser` a version bump?** The same answer, and an
uncomfortable one: your converter's behaviour includes the behaviour of
everything it calls, and here that is the interpreter you happen to be running.
`dossier`'s own PDF converters say so out loud — "it covers the *pinned* PDFium
too" — and pin accordingly. A standard-library parser is a defensible thing not
to pin; pretending it cannot change the artifact is not.

## Before you finish — what installing a converter changed

```console
$ pytest -q
FAILED tests/unit/test_R008_1__conversion_is_a_pure_function_of_its_input.py::
TestEveryMediaTypeInTheSampleIsCoveredOrNamed::
test_every_installed_converter_is_either_covered_or_a_named_exemption

AssertionError: ['text/csv', 'text/html'] has no sample payload, so every converter
claiming it is silently skipped by the rows above
```

Nothing is wrong. The suite runs its R8.1 conformance rows over *every installed
converter*, skipping any whose media type it has no sample payload for — and the
test above exists because a silent skip is the one outcome nobody would notice. A
converter that drops out of the purity check has to be named, with a note saying
where it is proved instead. Yours is not named, so the guard fires.

Both sides of that are load-bearing:

- The **suite is right**: what a run reads depends on the environment it ran in,
  and a test that shrugged at an unknown converter would let one arrive that is
  never checked for purity at all.
- The **package is right**: it is a workspace's dependency, and it has no
  business in the environment that runs the repository's tests.

```bash
VIRTUAL_ENV=$PWD/.venv uv pip uninstall dossier-html-playground
pytest -q     # green
```

And then the failure that is not about tests. Claiming a pair that is already
claimed:

```console
$ # media_type = "text/markdown" in csv_table.py, reinstalled
$ dossier convert incident-audit
6 document(s) have no converter:
  PLAY-2001-terminal-scan.pdf (application/pdf): two converters claim the same
  pair, and picking either would be picking by installation order:
  (text/markdown, markdown) is claimed by both markdown-text 1.0.0 and csv-markdown 0.1.0
  PLAY-2002-photocopy-no-text-layer.pdf (application/pdf): …
  PLAY-4001-payment-retries.html (text/html): …
  …
exit 2
```

Six for six, including two scans that have nothing to do with either converter
and an HTML export claimed by the other half of your own package. `_claims` in
`src/dossier/domain/conversion.py` refuses rather than choosing, and the comment
says why: the winner's id and version go into `K_convert`, so resolving the tie by
installation order would give two machines with the same packages two different
keys — and every stage key above them (R5.6).

---

## What to take to your own project

- Register capability, do not branch on it. A new format is a package somebody
  installs, never a case in a match statement in the core.
- Separate "we cannot read this kind of thing" from "we could not read this
  thing". They want different fixes and deserve different blast radii.
- A converter version is a cache invalidation key wearing a semver hat. Treat a
  dependency bump — including the standard library's — as a behaviour change
  unless you can show it is not.
- Refuse ambiguity at registration rather than resolving it at use. "Two of these
  claim the same thing" is a sentence a person can act on; picking one silently
  is a bug that surfaces months later as a cache that misses on one machine.
- Look at the converted text before you spend a model call on it.
