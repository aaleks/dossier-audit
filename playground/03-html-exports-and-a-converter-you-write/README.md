# 03 · Wiki exports, and a converter you write

**You will build:** a converter package of your own. It reads this wiki's HTML
exports the way this workspace wants them, is registered by entry point, and
answers only in the workspace that names it. Then a second converter in the same
package, which writes a CSV register as a markdown table, so that you can test
the argument for why `dossier`'s own does not.

**You will learn:** what a `(media type, kind)` pair is; the two kinds of
conversion failure, and why they behave differently; what happens when two
converters claim one pair, and how a workspace settles it; what a converter's
`version` actually buys; and why a converter belongs to a workspace rather than
to a machine.

**No model is needed.** Everything here is conversion. One optional step in
task 3 uses the stub model, to count calls rather than compare hashes.

---

## Background, in one paragraph

A snapshot is bytes as a source gave them. A stage reads text. Conversion is the
step between, and it is the first thing right of the hash boundary: from here on
everything is a pure function of content that is already frozen. A converter is
registered against the **pair** `(media type, kind)` — media type comes from the
snapshot, kind from the source's `convert:` list or from the default for that
media type (R8.10) — because neither half alone is enough. Media type cannot
express that one PDF is wanted as text and another as page images; a declared
kind cannot say what the bytes actually are.

> Eleven converters register with `dossier` itself, and every one of them does it
> through the entry-point group you are about to use (R8.7). Look at
> `[project.entry-points."dossier.converters"]` in the repository's
> `pyproject.toml`. `html-markdown` and `text-csv` are the two this folder needs,
> and they are recent: until R8.21 and R8.23 nothing claimed either pair, and
> this exercise was where you wrote them. Read
> `src/dossier/infrastructure/converters/html_markdown.py` at some point in this
> exercise. It is the converter yours will stand beside, and its docstring says
> what it decided and why.

---

## Task 1 — a mixed folder, and the two ways convert fails

Build `playground/work/03/` with a source reading one folder holding three
formats — PDFs, wiki pages exported as HTML, and a register exported as CSV:

```bash
mkdir -p playground/work/03/inbox/postmortems
cp playground/corpus/scans/*.pdf \
   playground/corpus/exports/* \
   playground/work/03/inbox/postmortems/
```

Declare the source with **no** `convert:` list — every document then gets the
default kind for its media type — give it the same one-step pipeline as exercise
02, sync, and then convert.

**Checkpoint.** `6 held · 6 converted · 0 cached`. Nothing was installed and
nothing was named: every pair in the folder is claimed by a converter that
ships. Find out which converter read which document. Each artifact under
`.dossier/cache/convert/` has a `.meta.json` beside it naming its converter and
its snapshot, and `resources/artifacts.py` follows those records for you (run it
from the workspace). Three converters read six documents. Look at the
register's row: its artifact's `sha256` is its snapshot's hash. Keep that for
task 4.

Now the failures. `resources/` holds two more files from the same postmortems
folder: `PLAY-4006-indexer-alerts.json`, an alert export, and
`PLAY-4005-connection-pool-exhaustion.html`, a page from an older wiki that
saves in Windows-1252. Before you copy them in, look up the media type the
folder connector will give each one (`MEDIA_TYPES` in
`src/dossier/domain/conversion.py`) and which converter claims it. Then copy
both into `inbox/postmortems/`, sync, and convert.

**Checkpoint.** Exit 2, and one document is named: the JSON, with the pair
nothing claims, `('application/json', 'markdown')`, and every pair that is
claimed. The Windows-1252 page is not mentioned at all. Neither are the six
documents converted a minute ago, although their artifacts are in the cache.

Take the JSON out, then sync and convert again.

**Checkpoint.** `7 held · 0 converted · 6 cached · 1 failed`, and exit 1. The
page fails, naming `html-markdown` and UTF-8, and the six are served from cache.

Why does one unclaimed media type stop documents that are fine, when a
converter that fails on one document stops only that document? And why was the
Windows-1252 page not even read the first time? The answer is in spec 008's
"Two kinds of failure" table. It is the difference between "this pipeline is not
configured to read what it was pointed at" and "one input is bad". Take the page
out too, and sync, before you go on.

## Task 2 — a converter of your own

Read `PLAY-4001`'s artifact. Its first line is the wiki's breadcrumb,
`Spaces / Site Reliability / Postmortems / 2026 / PLAY-4001`, and
`html-markdown` keeps it on purpose. R8.21 row 1 says why: a reader sees it, and
telling navigation from content by class name is the heuristic `trafilatura`
was rejected for. That is right for `dossier`, which reads every exporter there
is. It is not the only right answer for this workspace, which reads one. This
wiki always writes its trail as `<div class="breadcrumb">`. The trail says where
a page lives, and that changes whenever someone reorganises the wiki, while the
postmortem does not.

Write a converter that leaves it out. A converter is a package, not an edit to
`dossier`. Create one with:

- a class declaring `id`, `version`, `media_type` and `kind` — all four, or it is
  refused where it is registered (R8.2);
- a `convert(self, payload: bytes, options: Mapping[str, str]) -> bytes` method;
- a `[project.entry-points."dossier.converters"]` table pointing at the class.

Claim `(text/html, markdown)`, at version `0.1.0`, and give it an id of its own,
such as `play-html-markdown`. `dossier` tells two claims apart by id and
version, so a converter calling itself `html-markdown` would be taken for the
shipped one. `html.parser` in the standard library is enough. You need no
dependency at all, which is worth noticing beside `html-markdown`, which pins
two libraries exactly.

Rules to honour while you write `convert`, all of which come from R8.1 — the
artifact is a pure function of the snapshot bytes and the declared options:

- no clock, no locale, no environment variable, no file other than the input, and
  no network;
- the same bytes in must give the same bytes out, on any machine, forever.

Install it into the same environment (`uv pip install --no-deps -e <dir>`) and
check that `dossier` can see it:

```python
from dossier.infrastructure.converters.registry import installed_converters

for c in installed_converters():
    print(c.id, c.version, c.media_type, c.kind)
```

Then convert.

**Checkpoint.** Exit 2, and every document is refused, the scans and the
register included, although your converter claims neither of their pairs:

```
6 document(s) have no converter:
  PLAY-2001-terminal-scan.pdf (application/pdf): two converters claim the same pair, and picking either would be picking by installation order:
  (text/html, markdown) is claimed by both html-markdown 1.1.0 and play-html-markdown 0.1.0
A workspace settles it by naming one under converters: in sources.yaml (R8.13).
  …
```

Two claims on one pair are refused rather than settled by installation order.
The winner's id and version go into `K_convert`, so two machines with the same
packages would otherwise compute different keys (R5.6). The message says how a
workspace settles it. Add this line to the top of `sources.yaml`, beside
`sources:`, and convert again:

```yaml
converters: [play-html-markdown]
```

**Checkpoint.** `6 held · 3 converted · 3 cached`. The three exports were
converted again, under your converter's key. The scans and the register were
served from cache, because nothing about their pairs changed. Now misspell the
name once. It is refused before anything converts, and the message names every
installed converter (R8.13 row 4). A name that matched nothing would otherwise
be no choice at all.

Installing your package has stopped every workspace on this machine that
converts anything and names neither converter — including every workspace the
repository's test suite builds. `docling-markdown` claims the pair `pdf-markdown`
answers and does not cause this, because it declares itself **opt-in**. Find
`opt_in` in `src/dossier/infrastructure/converters/docling_markdown.py`. An
opt-in converter answers only where a workspace names it (R8.13). Add
`opt_in = True` to your class and convert. Then take your `converters:` line out
and convert again, and put it back.

**Checkpoint.** Neither run refuses anything. With the line in, your converter
answers; without it, `html-markdown` does. Both runs serve all six documents from
cache, because both converters' artifacts are already there. Write down what
opt-in saved you, and what it would cost someone who installed your package and
expected it to answer.

## Task 3 — read what a stage would actually see

Run `resources/artifacts.py PLAY-4001 --cat` from the workspace, then the same
for `PLAY-4003`. Each export now has two artifacts in the cache:
`html-markdown`'s from task 1, and yours. Naming a converter deleted nothing.

Compare `PLAY-4001`'s two notes. The breadcrumb is gone from yours. What else is
different? Would a span a model quoted from one be found in the other? The span
check folds whitespace and the markdown a converter writes around words
(R6.20), so find out rather than guess.

`PLAY-4003` is a Grafana panel shared as a page whose entire body is one `<img>`.
`html-markdown` wrote one line, `![panel-checkout-p99.png](panel-checkout-p99.png)`
(R8.22). Yours probably wrote nothing at all. Decide what the right behaviour is.
Should a converter fail on a page with no text, write nothing, or write what the
shipped one wrote? Before you settle it, find out whether a step runs for a
document whose note is empty. R6.21 and `_reads_nothing` in
`src/dossier/application/run.py` are the answer. Write down your decision and
the reason. You will act on it in task 5.

Then read `PLAY-2002-photocopy-no-text-layer.pdf`'s artifact, which nobody in
this exercise wrote: fifteen bytes, and they are a page anchor. `dossier`'s own
`pdf-markdown` had to answer the same question, in a format where "nothing"
still has a shape. Compare its answer with yours.

Last, the reason you wrote a converter at all. Move `PLAY-4001` in the wiki: in
`inbox/postmortems/PLAY-4001-payment-retries.html`, change the breadcrumb's
`Site Reliability` to `Payments`. Sync, convert, and list `PLAY-4001`'s artifacts
again.

**Checkpoint.** Sync reports one document changed, with its old and new hashes,
and convert converts it again. Your converter's artifacts for the old snapshot
and the new one have the same `sha256`. A step's key is computed over the note
it reads, not over the snapshot (spec 005), so every step over `PLAY-4001` would
be served from cache: moving the page costs no model call. Take your
`converters:` line out and convert. `html-markdown`'s note for the moved page
has a `sha256` of its own, and every step would ask about it again. Put the line
back.

What did leaving the breadcrumb out cost? Write that down too.

> **Optional: count the calls.** Start the stub model with this exercise's
> replies, which answer every document with four nulls, because here only the
> number of calls matters:
>
> ```bash
> .venv/bin/python playground/toolkit/stub_model.py \
>     --replies playground/03-html-exports-and-a-converter-you-write/resources/replies.json \
>     --port 8099 --log /tmp/dossier-calls-03.jsonl
> ```
>
> Point the workspace's `.env` at it as the playground README describes, run
> the pipeline, move the page again (to `Finance`, say), sync, and run once more.
> The second run reports `6 from cache`, and the call log does not grow.

## Task 4 — a register as a table

`text-csv` writes the register as the text it is. Its artifact is the file byte
for byte, which is why its `sha256` was the snapshot's own in task 1. A markdown
table is the obvious improvement, and spec 008 rejects it: read the **CSV**
paragraph of "An HTML page or a CSV file someone exported". Do not take that on
trust. Write the table.

Add a second converter to the same package, claiming `(text/csv, markdown)` and
writing the register as a markdown table. Same kind, different media type: a pair
is two halves, and only one of them moved. It claims the pair `text-csv`
answers, so declare it opt-in from the start. Reinstall the package: an entry
point is package metadata, so an editable install does not see a new one until
you do. Then convert.

**Checkpoint.** `6 held · 0 converted · 6 cached`. Your second converter is
installed and changed nothing, because it is opt-in. Name it beside the first,
`converters: [play-html-markdown, play-csv-table]`, and convert.
`1 converted · 5 cached`. Read the table.

Now test the argument. `locate_span` in `src/dossier/domain/grounding.py` is the
whole of the grounding check: a span is grounded if, once folded, it occurs in
the note the step read (R6.4). Convert the register both ways, and ask it about
three spans in each:

- one cell: `connection pool exhausted by a report query holding transactions open`
- a row as the table shows it: `| PLAY-4005 | 2026-06-21 | major | orders-api |`
- a row as the file has it: `PLAY-4005,2026-06-21,major,orders-api`

```python
from pathlib import Path

from dossier.domain.grounding import locate_span
from dossier.infrastructure.converters.registry import installed_converters

by_id = {c.id: c for c in installed_converters()}
register = Path("inbox/postmortems/PLAY-4004-incident-register.csv").read_bytes()
table = by_id["play-csv-table"].convert(register, {}).decode()
text = by_id["text-csv"].convert(register, {}).decode()
# locate_span(span, document_text=table), and the same against text
```

Then give your converter a register whose one cell holds a pipe,
`key,root_cause\nPLAY-4007,retries | no backoff\n`. What does the table write
for that cell, and is `retries | no backoff`, the cell as a person reads it,
grounded in it?

**Checkpoint.** Each row is grounded only in the note it was quoted from. The row
as the table shows it is not in the file, so a reviewer searching the register
for the evidence a model gave finds nothing. "Grounded" means "found in the text
the step was shown", and with a table that text is your converter's writing
rather than the register's. The pipe is worse: the table has to escape it, so a
right value quoted the way a person reads it is ungrounded, and scored incorrect
however right it is (R7.4). Decide whether this workspace names
`play-csv-table`, and write down why.

Then ask the question the pair invites: could you have claimed `(text/html,
page_images)` instead and rendered the page? You could register it. Before you
do, find out what a step actually receives for a non-`markdown` kind —
`PART_TYPE` in `src/dossier/domain/conversion.py` is the whole answer, and it is
exercise 10's subject.

## Task 5 — the promise a version makes

Act on what you decided about `PLAY-4003` in task 3. If you decided a page should
say what it shows, teach your converter to write an image as `html-markdown`
does, and raise its `version` from `0.1.0` to `0.2.0`. (If you decided something
else, make whatever change to its output your decision needs, and raise the
version all the same.) Convert.

**Checkpoint.** `3 converted · 3 cached`. The bump converted again exactly the
three artifacts your converter produced, and left the scans' and the register's
alone. Compare the `sha256` of `PLAY-4001`'s and `PLAY-4002`'s notes at `0.1.0`
and at `0.2.0`: the same bytes under new keys. Only `PLAY-4003`'s note changed.

Now set the version back to `0.1.0`, **keeping the new code**, and convert again.
Read `PLAY-4003`'s artifact.

**Checkpoint.** `0 converted · 6 cached`, and the note a step would now read for
`PLAY-4003` is `0.1.0`'s, which is empty. The cache served what `0.1.0` wrote,
although the code you have installed no longer writes it. Nothing reported it, and nothing could: the key says
"`play-html-markdown` `0.1.0` read these bytes", and that was once true. Put
`0.2.0` back and convert. Nothing is converted, because the `0.2.0` artifacts
were never deleted either: the cache is addressed by the key of the computation
that made an entry, so two versions of one converter sit side by side.

That is R5.4, and it is the whole mechanism behind the one promise a converter
author makes by hand: **raise the version whenever output could change for the
same input.** Nothing can enforce it. You have just watched what happens when it
is broken.

Worth asking yourself before you move on: your converter decides what becomes a
heading and what is dropped. Is a change to the classes it drops a version bump?
Is a new release of the standard library's `html.parser`?

---

## Before you finish

Two last refusals and a test run, and then the package comes out of this
environment.

First, name both HTML converters, `converters: [play-html-markdown,
html-markdown]`, and convert.

**Checkpoint.** It stops before converting anything, naming the pair and both
converters (R8.13 row 5). Either answer would be picking by the order a list was
written in. One converter per pair per workspace is what lets a manifest pin the
one that answered (R8.9), and a replay recompose every conversion from that pin
(R4.7). Put the line back.

Then run the repository's test suite, with your package still installed:

```bash
pytest -q
```

If both your converters are opt-in, it is green. That is not because the suite
ignored your package. The R8.1 purity rows run over every installed converter
that claims a media type the file has a sample payload for, and `text/html` and
`text/csv` both have one. So yours were converted twice in one process, and
once each in two processes with different locales, hash seeds and time zones,
and passed. Find their rows:

```bash
pytest -o addopts="" -rA tests/unit/test_R008_1__conversion_is_a_pure_function_of_its_input.py | grep play-
```

Now take `opt_in` off your HTML converter and run `pytest -q tests/acceptance`.
Which tests fail, and why do tests that never see an HTML file fail too? Put
`opt_in` back.

Then uninstall it (`uv pip uninstall dossier-html-playground`), and take the
`converters:` line out of this workspace's `sources.yaml`, because a name that
no installed package provides is refused by every command that plans or
converts. Your package is a dependency of one workspace. The environment that
runs the repository's tests has no business holding it, opt-in or not.

## Done when

- a converter package of your own, installed and registered by entry point, with
  two claims in it, both opt-in, and a workspace that names the one it wants;
- you can explain why an unclaimed pair stops documents that were fine, and a bad
  document does not;
- you can say what leaving the breadcrumb out saved, in model calls, and what it
  cost;
- you can say why the shipped CSV converter writes no table, with a span that
  shows it;
- exports converting, cached, and converting again on a version bump — and a
  cache you made lie by not raising one;
- you can say why installing a package can change what the test suite thinks,
  and what opt-in changes about that.

**Next:** [04 · Media types, default kinds, and the file dossier will not read](../04-media-types-and-the-file-dossier-will-not-read/).
