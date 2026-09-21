# 03 · Wiki exports, and a converter you write

**You will build:** a Python package that teaches `dossier` to read HTML exports
and CSV registers, and register it without touching a line of `dossier`.

**You will learn:** what a `(media type, kind)` pair is, the two kinds of
conversion failure and why they behave differently, what a converter's `version`
actually buys, and why a converter belongs to a workspace rather than to a
machine.

**No model is involved.** Everything here is conversion; the stub server can stay
off.

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

> `dossier` ships six converters, and two of them read PDFs — `pip install
> dossier[pdf]`. That is not a special case in the core: `pdf-markdown` and
> `pdf-images` are registered through exactly the entry-point group you are about
> to use, behind an extra, because PDFium is a large wheel with its own release
> cadence (R8.7). Read
> `src/dossier/infrastructure/converters/pdf_markdown.py` at some point in this
> exercise; it is the same shape as the package you are writing, written by
> someone who had to mean it.

---

## Task 1 — point a pipeline at a mixed folder and watch it refuse

Build `playground/work/03/` with a source reading one folder holding two
formats — PDFs `dossier` already reads, and wiki exports it does not:

```bash
mkdir -p playground/work/03/inbox/postmortems
cp playground/corpus/scans/*.pdf \
   playground/corpus/exports/* \
   playground/work/03/inbox/postmortems/
```

Declare the source with **no** `convert:` list — every document then gets the
default kind for its media type — give it the same one-step pipeline as exercise
02, sync, and then convert.

**Checkpoint.** `sync` is perfectly happy — it froze six documents and does not
care what is in them. `convert` exits 2 and names the four it cannot read, with
the pair nothing claims and the six pairs that *are* claimed.

Read that message closely, and notice what is **not** in the output: the two
scans. They are claimed, they would have converted, and they did not, because the
whole run stopped. Why does one unclaimed media type stop documents that are
fine, when a converter that fails on one document stops only that document? The
answer is in spec 008's "Two kinds of failure" table, and it is the difference
between "this pipeline is not configured to read what it was pointed at" and
"one input is bad".

## Task 2 — write the converter

A converter is a package, not an edit to `dossier`. Create one with:

- a class declaring `id`, `version`, `media_type` and `kind` — all four, or it is
  refused where it is registered (R8.2);
- a `convert(self, payload: bytes, options: Mapping[str, str]) -> bytes` method;
- a `[project.entry-points."dossier.converters"]` table pointing at the class.

Claim `(text/html, markdown)` and pull the text out of the export.
`html.parser` in the standard library is enough; you need no dependency at all,
which is worth noticing beside the `pdf` extra — the mechanism costs nothing when
the converter is small.

Install it into the same environment (`uv pip install --no-deps -e <dir>`) and
check that `dossier` can see it:

```python
from dossier.infrastructure.converters.registry import installed_converters

for c in installed_converters():
    print(c.id, c.version, c.media_type, c.kind)
```

Rules to honour while you write `convert`, all of which come from R8.1 — the
artifact is a pure function of the snapshot bytes and the declared options:

- no clock, no locale, no environment variable, no file other than the input, and
  no network;
- the same bytes in must give the same bytes out, on any machine, forever.

Then convert. **Checkpoint.** The message is one line shorter — three exports have
gone from it, and `(text/html, markdown)` has appeared in the claimed pairs — and
the run still exits 2, over `PLAY-4004-incident-register.csv` alone. Nothing was
written: every document is resolved *before* any is converted, so one unclaimed
pair still costs you the whole run. That is Task 4.

## Task 3 — read what a stage would actually see

Find the artifacts under `.dossier/cache/convert/` and read the one for
`PLAY-4003-latency-dashboard-export.html`. (Each artifact has a `.meta.json`
beside it naming the converter and the snapshot, which is how you tell which is
which.)

**Checkpoint.** It is empty. That export is a Grafana panel shared as a page
whose entire body is one `<img>`, and this is the surprise `dossier convert`
exists to show you *before* a model call is made rather than after twenty of
them. Decide what you think the right behaviour is: should a converter fail on a
page with no text, or return nothing? Write down your answer and the reason.

Then read `PLAY-2002-photocopy-no-text-layer.pdf`'s artifact, which nobody in
this exercise wrote: fifteen bytes, and they are a page anchor. `dossier`'s own
`pdf-markdown` reached the same answer as the one in the solution, in a format
where "nothing" still has a shape. Compare the two, then the solution.

## Task 4 — a second pair from the same package

Add a second converter to the same package claiming `(text/csv, markdown)` and
turn the register into a markdown table. Same kind, different media type: a pair
is two halves and only one of them moved.

**Checkpoint.** `6 held · 6 converted · 0 cached`, then `0 converted · 6 cached`
on a second run. Six documents, three converters, one kind.

Then ask the question the pair invites: could you have claimed `(text/html,
page_images)` instead and rendered the page? You could register it. Before you
do, find out what a step actually receives for a non-`markdown` kind —
`PART_TYPE` in `src/dossier/domain/conversion.py` is the whole answer, and it is
exercise 10's subject.

## Task 5 — the promise a version makes

Raise your HTML converter's `version` from `0.1.0` to `0.2.0` and convert again.
Then put it back and convert once more.

**Checkpoint.** The bump re-converts exactly the three artifacts that converter
produced and leaves the scans' and the register's alone. Putting the version back
serves the original entries from cache — they were never deleted.

That is R5.4, and it is the whole mechanism behind the one promise a converter
author makes by hand: **raise the version whenever output could change for the
same input.** Nothing can enforce it. A converter that quietly starts keeping
`<table>` markup without a bump leaves a cache full of artifacts claiming to be
something they are not, and no test anywhere will notice.

Worth asking yourself before you move on: your converter decides what becomes a
heading and what is dropped. Is a change to `DROPPED` a version bump? Is a change
to the standard library's `html.parser`?

---

## Before you finish

Two things happen when a converter is installed into the environment that also
runs the repository's test suite, and both are worth seeing.

```bash
pytest -q
```

One unit test fails, and it is worth reading rather than working around — it
asserts that every installed converter is either covered by the R8.1 purity
sample or *named* as an exemption, and your package has changed the answer for
the whole environment. Uninstall it (`uv pip uninstall dossier-html-playground`)
and the suite is green again.

Then the failure that is not about tests at all. Change your CSV converter's
`media_type` to `text/markdown`, reinstall, and run `dossier convert` again.

**Checkpoint.** Every document fails, including the two scans, which have nothing
to do with either converter. A pair matches at most one converter, and two
claims on one pair are refused rather than resolved by installation order —
because the winner's id and version go into `K_convert`, so two machines with the
same packages would otherwise compute different keys (R5.6). Put it back.

## Done when

- a converter package of your own, installed and registered by entry point, with
  two claims in it;
- exports converting, cached, and re-converting on a version bump;
- you can explain why an unclaimed pair stops documents that were fine, and a bad
  document does not;
- you can say why installing a package changed what the *test suite* thinks, and
  where a converter therefore belongs.

**Next:** [04 · Media types, default kinds, and the file dossier will not read](../04-media-types-and-the-file-dossier-will-not-read/).
