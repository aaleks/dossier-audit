# Images, PDFs and visual evidence — the agreed shape

Written 2026-09-18, after reviewing `image_manage.md`, `AGENTS.md` and
`brainstorm_session.md` against the specs and the code.

Nothing here is a spec yet. It is the set of decisions `/discover` should start
from, and the reasoning that produced them, so the reasoning does not have to be
had twice.

## Triage of the three input documents

`brainstorm_session.md` and `AGENTS.md` both challenge an architecture shaped
`PDF → chunks → embeddings → RAG`. `dossier` is not that: no chunks, no
embeddings, no vector store, no retrieval step. Their *conclusions* (§12, §26 —
"at 25 documents a structured taxonomy plus an LLM beats embeddings") are right
and are already the de facto design.

AGENTS.md's evidence model is mostly built already, under other names:

| AGENTS.md | dossier today |
|---|---|
| Source | `sources.yaml` entry + connector (spec 001) |
| Document | ledger row + immutable snapshot (spec 002, R0.2) |
| Claim | a field's `value` |
| Evidence | `source.span`, located by string search (R6.4) |
| AuditCriterion | a field declaration + the step prompt (R6.10 — data, not Python) |
| AuditFinding | the scored field (spec 007) |
| Presence / Evidence / Sufficiency | `value != null` / `grounded` / the judge (R7.17) |
| "don't make Markdown canonical" | already true; canonical is the snapshot, markdown is one *kind* |
| "extract once, reuse many times" | the cache key chain (spec 005) |

So `image_manage.md` is the document that matters, and it is accurate.

## What stays exactly as it is

**`sync`, the ledger, the watermark and the hash.** A vision model is a consumer
of frozen bytes, not a change to how bytes are frozen.

**The snapshot freeze, including for PDFs.** Holding a *reference* to the source
instead was considered and rejected: the freeze is what makes replay, cache keys
and "which exact bytes produced this answer" true, and with visual evidence that
matters more, not less — a vision description is expensive and irreproducible, so
if the exact bytes cannot be re-shown the description can never be audited.

The storage worry behind that idea is already answered by the existing split:
snapshots are content-addressed and dedup, and **rendered page images are not
snapshots — they are convert artifacts, cache, disposable under R5.9.**

## The hole, which the specs already name

Spec 008, R8.4 counter-example 4:

> a stage declaring `input: documents` in a pipeline whose source produces two
> kinds → *not resolved here; which kind a stage reads is a pipeline question
> (spec 003), not a conversion one*

Spec 003 never answers it. `ConvertReport.text`
(`src/dossier/application/convert.py:116-119`) keeps only the `markdown` kind and
drops the rest. `page_images` is a real, counted, keyed, invalidatable artifact
that **no stage can name**. The vision question is not "may a converter call a
model" — it is "a step cannot say which kind it reads".

## Decision 1 — the vision call is a step, not a converter

Not for purity reasons. For the reason spec 011 already records: a vision call's
cache key must contain the model id (R5.3), the prompt (R5.2) and the input
artifact hash. That *is* a stage key. Putting it in a converter means `K_convert`
re-derives what specs 005 and 009 already derive — a second way of arriving at a
figure, which is the one thing spec 011 forbids.

A converter `version` means "the code changed". A vision converter's version
would have to mean "the model changed", and nothing would enforce it.

## The target shape

```
snapshot (frozen bytes, hashed)                     ← unchanged
   │
   ├── convert  (pure, no model, no network)
   │     (application/pdf, markdown)    → text with page anchors
   │     (application/pdf, page_images) → N page renders, one container artifact
   │     (image/png, markdown)          → OCR text            [dossier[ocr]]
   │     (image/png, page_images)       → the image itself
   │
   ├── describe step   input: documents@page_images   mode: per_part
   │     model call, vision, cached by stage key, MLflow-traced
   │     → text per page
   │
   └── extract step    input: [documents, describe]
         span found in converted document text → grounded   (page derived)
         span found only in describe output    → described  (page image named)
         found in neither                      → ungrounded
```

## Decision 2 — page images: one container artifact, `mode: per_part`

`convert` emits **one** artifact for `(application/pdf, page_images)`: a
deterministic container (sorted entries, fixed timestamps) so R8.1's
byte-identical promise and R8.4's one-conversion-one-artifact both hold
untouched.

The `describe` step gains `mode: per_part`, so the **stage** key carries the page
id:

```
convert:   (pdf, page_images) → 1 artifact, 1 K_convert
           container holds page-001.png .. page-040.png

describe:  mode: per_part
           key = (prompt, model, artifact, page-007)
           → 40 calls, 40 cache entries, retry page 7 alone
```

Spec 005 gains a part dimension; spec 008 gains no new concept. Buys per-page
cache, per-page retry and per-page cost.

Cost lever, deterministic and left of the model: `pdf-images` takes
`options: {pages: all | figures-only}`, so pages with no figure and a healthy
text layer are never rendered and never described. Options are already in
`K_convert` (R8.1 counter-example 4).

## Decision 3 — grounding gains `described`, judged by a vision judge

```
grounded    span found in the converted document text
described   span found only in a describe step's output
            → the record names the page image it came from
            → judged by a VISION judge, shown that page image
ungrounded  found in neither

report:  12 grounded · 3 described · 1 ungrounded
```

`described` is counted **separately** from `grounded` in spec 007, never folded
into it. The judge is a vision judge so that the calibrated question — "is this
candidate supported by the document" — stays literally true; a text judge shown
only the description is a model agreeing with another model's hallucination.

Spec 007's calibration is already per (field, judge), so the vision judge needs
its own calibration sample and its own agreed threshold, and nothing structural
moves.

Per the repository's rule-id policy this is a **new rule superseding R6.4 in
place**, not an edit to R6.4's text.

## Decision 4 — converters ship, as extras

```
pip install dossier            # markdown-text, text-plain
pip install dossier[pdf]       # pdf-markdown, pdf-images
pip install dossier[ocr]       # image-markdown, and pdf-markdown's ocr option
```

No spec change. R8.7 counter-example 3 blesses it outright: "`pdf-markdown`
shipping in this package — allowed; it registers through the same group as any
third party, with no special case." Shipping the converters people actually need
was never a spec question; it was work nobody did.

Also in this slice: `image/png` and `image/jpeg` in `MEDIA_TYPES` defaulting to
`page_images`, and `text/plain`. That closes spec 008's open question 1 and
playground exercise 04's question at the same time.

**Declarative / YAML converters were considered and rejected.** A converter
shelling out to an external binary cannot keep R8.1's promise the way a pinned
package can, and the manual version-bump discipline — already the one thing
nothing enforces — gets strictly worse. A converter is fifteen lines of Python;
the problem was never the class, it was having to write the obvious ones
yourself. A `dossier new converter` scaffold covers the rest.

## Also worth doing, and cheap

**Make `source.page` derived rather than claimed.** `SourceRef.page` already
exists (`src/dossier/domain/schemas.py:26`) and *nothing verifies it*: the model
asserts a page number and no code has ever disagreed with it. Have `pdf-markdown`
emit a stable page anchor and have the span locator return the enclosing anchor.
Then a model claiming p.3 for a span that lives on p.8 is a grounding failure.

One converter change plus one domain rule, and it is what turns dossier into what
AGENTS.md §5 asks for (`PM-123.pdf p.8`).

## What is not being built

Embeddings, pgvector, clustering, LangGraph, an agent, a graph database. At 25–40
documents, clustering 25 points produces groups nobody can validate, and `run`'s
cached DAG is already what a workflow engine would sell — minus a dependency and
minus a second place where the graph is defined.

One idea from `brainstorm_session.md` §26 is worth keeping, though. Cross-document
analysis today is only `mode: aggregate`: one model call over everything, asked to
*count*. "Which criteria are consistently poorly evidenced across 20 postmortems"
is a `GROUP BY`, not a prompt. A deterministic rollup with the model only
*explaining* the numbers is cheaper, reproducible and auditable.

Constraint on that, when it is written: **R0.11 says nothing under `runs/` is ever
read back.** A rollup sources from the cache by key via the manifest, never from
the run directory.

## Slice order

| # | Slice | Spec cost |
|---|---|---|
| 1 | `text-plain`, image media types, `dossier[pdf]` converters | none |
| 2 | `dossier[ocr]` | none |
| 3 | `source.page` derived from a page anchor | spec 006, one rule |
| 4 | `input: documents@page_images`, and a named kind no source produces stops at resolution | specs 003, 004 |
| 5 | `ModelClient` image parts; a provider that cannot take them refuses before the first call (R9.4's shape) | spec 009 |
| 6 | `mode: per_part` and the `describe` step | specs 003, 005 |
| 7 | `described` grounding state, counted separately | specs 006, 007 |
| 8 | the vision judge and its calibration | spec 007 |

1–3 are pure win and touch no rule. 4–8 is one multi-spec `/discover`.

**Prerequisite for 7.** A real gold case whose answer lives *only* in a chart,
added to `specs/_fixtures.md` — never an incident key invented ad hoc. Without it
the `described` threshold is a number nothing measured, which is exactly the
failure `/quality` already caught once.

## Resolved, 2026-09-18

### 1 — a `described` field shows all three

The span, the description sentence it was found in, **and** the page image's
cache key.

The third state exists so a reader can tell "the document says it" from "a model
says the picture says it". Showing only the description reproduces exactly the
confusion the state was invented to remove; showing only the image makes the
reader redo the model's work by hand. The image is named by its **cache key**
rather than a path under `runs/`, because nothing under `runs/` is ever read back
(R0.11) and the key is the part that survives.

### 2 — the vision judge carries its own threshold

Declared per (field, judge), exactly as spec 007 already requires.

A `described` field inheriting the text judge's threshold would print a number
measured against a different question. That is the R7.15 failure verbatim: a
calibration that is missing, short or stale withholds the field, and a
calibration measured on *other evidence* is stale in the only sense that matters.

### 3 — `pypdfium2`, for both PDF converters

**Recommendation:** `pypdfium2` claims `(application/pdf, markdown)` and
`(application/pdf, page_images)` from one pinned wheel.

*Pros.* One dependency does text extraction **and** page rendering, so both
converters share a single version-bump obligation. BSD-3/Apache-2.0, no copyleft.
Prebuilt wheels on Windows, macOS and Linux with no system binary to install.
PDFium is Chrome's renderer, so page-render fidelity is the best available.

*Cons.* A C extension, so an exotic platform can fail to install. PDFium's text
extraction is not layout-aware, so complex tables come out worse than
`pdfplumber` would manage.

*Alternatives considered.* **PyMuPDF** — best-in-class extraction and rendering,
rejected on licence: AGPL reaches downstream users of dossier, which is not a
cost this project may impose on its own consumers. **pdfminer.six** — pure
Python and layout-aware, but text only; pairing it with a renderer means two
dependencies and two version-bump obligations. **pypdf** — already present as a
dev dependency, but rendering is out of scope and its extraction is weaker.

*Why this one.* The deciding factor is not extraction quality, it is that one
library covers both converters. Two libraries means two hand-maintained version
bumps on the single promise in this repository that **no test can enforce**
(spec 008, "Versioning"). Halving the number of places that promise can be broken
is worth more than better table extraction, which a later `options:` or a third
converter can add without disturbing anything.

### 4 — `figures-only` gets no rule of its own

It is an option. Options are already in `K_convert` (R8.1 counter-example 4) and
the converter's `version` covers its behaviour. A rule for it would be spec 008
describing one converter's internals, which is the coupling R8.7 exists to
prevent.

### 5 — OCR engine: `rapidocr-onnxruntime`, not `pytesseract`

Decided here because it arrives with the `dossier[ocr]` slice and is the same
kind of decision as 3.

`pytesseract` needs a Tesseract binary that dossier cannot pin. The converter's
`version` would then mean different behaviour on different machines while
claiming the same `K_convert` — a direct R8.1 violation that **no test could
catch**, because every machine would be self-consistent. `rapidocr-onnxruntime`
ships its ONNX weights inside the pip package, so the package version pins the
behaviour, which is what `version` is required to mean.

*Cons, accepted:* a larger wheel and an `onnxruntime` dependency. It stays behind
an extra, so nobody who does not want it pays for it.
