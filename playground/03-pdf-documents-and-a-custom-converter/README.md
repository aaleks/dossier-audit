# 03 · PDF documents, and a converter you write

**You will build:** a Python package that teaches `dossier` to read PDFs, and
register it without touching a line of `dossier`.

**You will learn:** what a `(media type, kind)` pair is, the two kinds of
conversion failure and why they behave differently, what a converter's `version`
actually buys, and why `dossier convert` exists at all.

**No model is involved.** Everything here is conversion; the stub server can stay
off.

---

## Background, in one paragraph

A snapshot is bytes as a source gave them. A stage reads text. Conversion is the
step between, and it is the first thing right of the hash boundary: from here on
everything is a pure function of content that is already frozen. A converter is
registered against the **pair** `(media type, kind)` — media type comes from the
snapshot, kind from the source's `convert:` list — because neither half alone is
enough. Media type cannot express that one PDF is wanted as text and another as
page images; a declared kind cannot say what the bytes actually are.

---

## Task 1 — point a pipeline at PDFs and watch it refuse

Build `playground/work/03/` with a source reading a folder of PDFs. Use the
repository's own fixtures plus the playground's two scans:

```bash
mkdir -p playground/work/03/inbox/postmortems
cp tests/fixtures/documents/postmortems/pdf/INC-4977-*.pdf \
   tests/fixtures/documents/postmortems/pdf/INC-5102-*.pdf \
   playground/corpus/scans/*.pdf \
   playground/work/03/inbox/postmortems/
```

Declare the source with `convert: [markdown, page_images]`, give it the same
one-step pipeline as exercise 02, sync, and then convert.

**Checkpoint.** `sync` is perfectly happy — it froze four PDFs and does not care
what is in them. `convert` exits 2 and names every document it cannot read, with
the pair nothing claims and the pairs that *are* claimed.

Read that message closely. Why does one unclaimed media type stop the whole run,
when a converter that fails on one document stops only that document? The answer
is in spec 008's "Two kinds of failure" table, and it is the difference between
"this pipeline is not configured to read what it was pointed at" and "one input
is bad".

## Task 2 — write the converter

A converter is a package, not an edit to `dossier`. Create one with:

- a class declaring `id`, `version`, `media_type` and `kind` — all four, or it is
  refused where it is registered (R8.2);
- a `convert(self, payload: bytes, options: Mapping[str, str]) -> bytes` method;
- a `[project.entry-points."dossier.converters"]` table pointing at the class.

Install it into the same environment (`uv pip install --no-deps -e <dir>` if
`pypdf` is already there from the dev group) and check that `dossier` can see it:

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

Then convert. **Checkpoint.** `4 held · 4 converted · 0 cached`, then `0
converted · 4 cached` on a second run.

## Task 3 — read what a stage would actually see

Find the artifacts under `.dossier/cache/convert/` and read the one for
`PLAY-2002-photocopy-no-text-layer.pdf`.

**Checkpoint.** It is empty — or near enough. That PDF has an image and no text
layer, and this is the surprise `dossier convert` exists to show you *before* a
model call is made rather than after twenty of them. Decide what you think the
right behaviour is: should a converter fail on a PDF with no text, or return
nothing? Write down your answer and the reason, then compare with the solution.

## Task 4 — a second kind from the same snapshot

Add a second converter claiming `(application/pdf, page_images)` and extract the
images each PDF embeds. `PLAY-2001-terminal-scan.pdf` carries one; the
repository's fixtures carry none, which is itself a useful thing to see.

**Checkpoint.** `4 held · 8 converted` — two artifacts per document, two keys,
two cache entries. Now find where those page images end up in the *run*, and you
will find that they do not: only the `markdown` kind becomes text a stage reads
and grounds spans in. Page images are an addition to text, never a replacement.

## Task 5 — the promise a version makes

Raise your markdown converter's `version` from `0.1.0` to `0.2.0` and convert
again. Then put it back and convert once more.

**Checkpoint.** The bump re-converts exactly the artifacts that converter
produced and leaves the other converter's alone. Putting the version back serves
the original entries from cache — they were never deleted.

That is R5.4, and it is the whole mechanism behind the one promise a converter
author makes by hand: **raise the version whenever output could change for the
same input.** Nothing can enforce it. A converter that quietly improves its table
extraction without a bump leaves a cache full of artifacts claiming to be
something they are not, and no test anywhere will notice.

Worth asking yourself before you move on: your converter's output depends on
`pypdf`. Is bumping the pinned `pypdf` range a version bump for *your* converter?

---

## Before you finish

Run the repository's test suite with your converter still installed:

```bash
pytest -q
```

One acceptance test fails, and it is worth reading rather than working around —
it asserts which converters a manifest recorded, and your package has changed the
answer for the whole environment. Uninstall it (`uv pip uninstall
dossier-pdf-playground`) and the suite is green again. What that tells you about
where a converter lives is the last lesson of this exercise; the solution says
the rest.

## Done when

- a converter package of your own, installed and registered by entry point;
- PDFs converting, cached, and re-converting on a version bump;
- you can explain why an unclaimed pair stops everything and a bad document does
  not;
- you can say why installing a package made a test about a *manifest* fail.

**Next:** [04 · Plain text, images and unrecognised media types](../04-plain-text-and-unrecognised-media-types/).
