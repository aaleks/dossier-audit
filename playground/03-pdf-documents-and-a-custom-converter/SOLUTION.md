# 03 · Solution

Every command below was run against this repository. The output shown is the
output it produced.

## Run the prepared answer

```bash
# the converter package, installed into the same environment
VIRTUAL_ENV=$PWD/.venv uv pip install --no-deps -e \
  playground/03-pdf-documents-and-a-custom-converter/solution/dossier_pdf_playground

mkdir -p playground/work/03/inbox/postmortems
cp -r playground/03-pdf-documents-and-a-custom-converter/solution/workspace/. playground/work/03/
cp tests/fixtures/documents/postmortems/pdf/INC-4977-*.pdf \
   tests/fixtures/documents/postmortems/pdf/INC-5102-*.pdf \
   playground/corpus/scans/*.pdf \
   playground/work/03/inbox/postmortems/

cd playground/work/03
../../../.venv/bin/dossier sync incident-audit
../../../.venv/bin/dossier convert incident-audit
```

`--no-deps` because `pypdf` is already installed here through the repository's
dev group. Without it, `uv pip install -e …` resolves `pypdf` itself, which needs
a network.

---

## Task 1 — the refusal

```console
$ dossier sync incident-audit
postmortems-pdf  0 known · 0 changed · 4 new -> 4 fetched
ledger updated · 4 new snapshots · 0 tombstoned

$ dossier convert incident-audit
4 document(s) have no converter:
  INC-4977-postgres-wal-disk-full.pdf (application/pdf): nothing converts
  ('application/pdf', 'markdown'). Claimed pairs: ['(text/markdown, markdown)']. A converter
  is added by installing a package that declares a dossier.converters entry point.
  INC-5102-orders-api-oom-postmortem.pdf (application/pdf): …
  PLAY-2001-terminal-scan.pdf (application/pdf): …
  PLAY-2002-photocopy-no-text-layer.pdf (application/pdf): …
exit 2
```

Sync did not care. It fetched bytes, hashed them, recorded `application/pdf` from
the extension table and wrote four snapshots — everything it promises to do, with
no opinion about what a PDF contains.

Convert did care, and stopped **everything**:

| What happened | Blast radius | Because |
|---|---|---|
| no converter claims a media type | the whole run stops | the pipeline is not configured to read what it was pointed at. Nothing about the run is well-defined, and the fix is an installation, not a retry |
| a converter fails on one document | that document only | the configuration is right and one input is bad. An audit over nine of ten documents is useful, provided it says which one is missing |

Collapsing those one way turns an installation problem into nine mysterious
per-document errors; the other way turns one corrupt PDF into a run that produced
nothing. The message lists the claimed pairs because that turns the error into
its own fix: you can see immediately that `markdown` is claimed for
`text/markdown` and that nothing has claimed `application/pdf` at all.

## Task 2 — the converter

`solution/dossier_pdf_playground/` is a complete package:

```
pyproject.toml
src/dossier_pdf_playground/__init__.py
src/dossier_pdf_playground/markdown.py     (application/pdf, markdown)
src/dossier_pdf_playground/images.py       (application/pdf, page_images)
```

The registration, in `pyproject.toml`:

```toml
[project.entry-points."dossier.converters"]
pdf-markdown = "dossier_pdf_playground.markdown:PdfMarkdownConverter"
pdf-page-images = "dossier_pdf_playground.images:PdfPageImagesConverter"

dependencies = ["pypdf>=6.0"]
```

The dependency line is the argument for the whole mechanism. A PDF converter is a
large library with its own release cadence; pinning every `dossier` pipeline in
existence to it because it lives in the core package is exactly the coupling
entry points avoid. Note also what is *not* here: no edit to any file under
`src/dossier/`, and no match statement anywhere (R8.7, and `tests/architecture/`
has a test that fails if one appears).

The converter itself, in full:

```python
class PdfMarkdownConverter:
    id = "pdf-markdown"
    version = "0.1.0"
    media_type = "application/pdf"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        try:
            reader = PdfReader(io.BytesIO(payload))
        except Exception as error:
            raise ValueError(f"{self.id} could not read the PDF: {error}") from error

        pages = []
        for number, page in enumerate(reader.pages, start=1):
            pages.append(PAGE_MARKER.format(number=number).strip("\n"))
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages).encode("utf-8")
```

Three things it does not do, each of them R8.1: it reads no clock, it opens no
file other than the bytes it was handed, and it asks nothing over the network.
`K_convert` claims an artifact is determined by the snapshot hash, the converter
id, its version and its options. If a converter consults anything else, the key
is a lie — the cache serves text that no longer matches what the converter would
produce today, nothing detects it, and every stage above inherits the error with
a provenance record that looks correct.

`options` is accepted and unused. Taking the argument keeps every converter
called the same way, and options are part of the key, so an option nobody reads
still produces its own cache entry rather than quietly sharing one.

```console
$ python -c "
from dossier.infrastructure.converters.registry import installed_converters
for c in installed_converters(): print(c.id, c.version, c.media_type, c.kind)"
pdf-markdown 0.1.0 application/pdf markdown
pdf-page-images 0.1.0 application/pdf page_images
markdown-text 1.0.0 text/markdown markdown

$ dossier convert incident-audit
postmortems-pdf  4 held · 8 converted · 0 cached
cache updated · 8 converted · 0 cached

$ dossier convert incident-audit
postmortems-pdf  4 held · 0 converted · 8 cached
cache updated · 0 converted · 8 cached
```

## Task 3 — what a stage would actually see

```console
$ # the artifact for the postmortem fixture
$ head -c 90 .dossier/cache/convert/3d/6d/3d6d2383…
<!-- page 1 -->

Spaces  /  Site Reliability  /  Postmortems  /  2026  /  INC-4977

$ # the artifact for the photocopy
$ cat .dossier/cache/convert/bc/d6/bcd62a77…
<!-- page 1 -->

$ wc -c < .dossier/cache/convert/bc/d6/bcd62a77…
17
```

Seventeen bytes: a page marker and nothing else. `PLAY-2002` is an image of a
page with no text layer, so there is no text to extract.

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

What the *pipeline* should do about a PDF with no text layer — OCR it, exclude
it, or fail the run — is a question for whoever owns the corpus, and in this
repository it would start as a spec amendment rather than as a `try/except`.

## Task 4 — a second kind from the same snapshot

```console
$ python - <<'PY'
import json, pathlib
p = pathlib.Path(".dossier/cache/convert/0f/61/0f61a9d7…")
d = json.loads(p.read_text())
for page in d["pages"]:
    for image in page["images"]:
        print(page["page"], image["name"], image["bytes"], "bytes")
PY
1 Im1.png 116 bytes
```

Eight artifacts for four documents: `markdown` and `page_images` for each, under
two keys, from two converters. The repository's own fixtures produce
`{"pages":[{"images":[],"page":1},{"images":[],"page":2}]}` — they are generated
from text and embed no images at all, which is worth seeing: an empty answer from
a converter that worked is different from a converter that could not run.

**Where do the page images go in a run?** Nowhere. Only the `markdown` kind
becomes the text a stage reads, because a stage grounds spans in text and page
images are not text (`ConvertReport.text` in
`src/dossier/application/convert.py`). The artifact is still a real cache entry
with a real provenance record — counted by `convert`, keyed by `K_convert`,
invalidated by a version bump — and no stage is shown it.

That is a position, not a limitation: page images arrive as an addition to text,
never instead of it. A pipeline that wants to *reason* over them needs a step
whose input is that artifact, which is a spec conversation nobody has had yet.

## Task 5 — the promise a version makes

```console
$ # version = "0.2.0" in markdown.py
$ dossier convert incident-audit
postmortems-pdf  4 held · 4 converted · 4 cached
cache updated · 4 converted · 4 cached

$ # version back to "0.1.0"
$ dossier convert incident-audit
postmortems-pdf  4 held · 0 converted · 8 cached
cache updated · 0 converted · 8 cached
```

Exactly four re-converted: the four `pdf-markdown` produced. `pdf-page-images`
did not move, so its four artifacts were served from cache — a version
invalidates "every artifact that converter produced and nothing else" (R5.4).

Reverting the version served the *original* entries again, because nothing was
deleted. The cache is addressed by the key of the computation that made an entry,
not by content, so two versions of one converter coexist happily.

**Is bumping `pypdf` a version bump for your converter?** Yes, if the text it
extracts could change — and for a PDF library that is the normal case, not the
exceptional one. The obligation is on output, not on your own source: "raise the
version whenever output could change for the same input". Your converter's
behaviour includes the behaviour of everything it calls. A dependency range like
`pypdf>=6.0` with a `version` that never moves is a promise you cannot keep.

## Before you finish — the test your package broke

```console
$ pytest -q
FAILED tests/acceptance/test_R004_7__replay_reproduces_a_past_run.py::
TestAReplayIsPinnedToTheConvertersItUsed::test_the_manifest_records_the_converters_the_run_used
```

```python
converters = manifest["plan"]["converters"]
assert {c["id"] for c in converters} == {"markdown-text"}
```

Nothing is wrong. A run records the converters it actually had available, and
your two are now among them — so the manifest holds three ids and the test, which
was written against an environment with one, fails.

Both sides of that are load-bearing:

- The **manifest is right**: recording converter versions is what makes a replay
  reproducible "without the installed packages agreeing", which is the difference
  between a manifest that describes a run and one that merely describes a
  pipeline (the test's own docstring).
- The **test is right**: it pins what the environment provides, and the
  environment is an input to a run. A test that shrugged at extra converters
  would not notice the day one arrived that changed everyone's keys.

So: uninstall when you are done, or install into a throwaway virtualenv.

```bash
VIRTUAL_ENV=$PWD/.venv uv pip uninstall dossier-pdf-playground
pytest -q     # green
```

And notice what this rules out for real projects: a converter is not something
you install globally and forget. It is a dependency of a *workspace*, it changes
what every run in that environment records, and it belongs in whatever file pins
that environment.

---

## What to take to your own project

- Register capability, do not branch on it. A new format is a package somebody
  installs, never a case in a match statement in the core.
- Separate "we cannot read this kind of thing" from "we could not read this
  thing". They want different fixes and deserve different blast radii.
- A converter version is a cache invalidation key wearing a semver hat. Treat a
  dependency bump as a behaviour change unless you can show it is not.
- Look at the converted text before you spend a model call on it.
