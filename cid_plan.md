# CID masking — a plan for `/discover`

**Status:** Draft plan, not a spec. Nothing here is a rule yet.
**Written:** 2026-10-02, against `1bfb544`.
**Next step:** `/discover` with this file. It should produce `specs/020-cid-masking.md`
and the amendments listed in §6.

## 1. What this is for

Documents are fetched and frozen **as they are**: sync, the snapshot store and
conversion do not change. A pipeline can declare **CID masking**, and it is
**off unless declared**. When a pipeline declares it, nothing that pipeline
sends to a model and nothing it writes to the index carries client identifying
data:

- `dossier run` (and a try, `--doc`) asks the model through OpenWebUI with masked text only;
- `dossier embed` embeds masked text only and writes masked text only to pgvector;
- `dossier eval` and `dossier calibrate` show a judge masked text only;
- `dossier search` over that index never needs the real values.

The masking happens on this machine, with Presidio, before anything leaves.

**CID** is read here as *Client Identifying Data*, the banking term: a client's
name, address, account or IBAN, client or partner number, e-mail, phone, date of
birth and identity document numbers. If it means only *client id numbers*,
D1 shrinks to pattern recognisers and most of the NER cost disappears. `/discover`
confirms this first.

### What the guarantee is, and what it is not

Two claims, kept apart:

| Claim | Kind | Can be proved |
|---|---|---|
| **The mechanism.** Every span the masker detects is replaced in everything a masked pipeline sends to a model, writes to the index or records to MLflow. With masking declared, no path sends unmasked text, and anything that cannot be masked is refused. | deterministic | yes, with `==`, offline, with a fake masker and canary values |
| **The detection.** The masker finds the CID in real incident text. | evaluated | no. Presidio's NER is statistical. Its recall can only be **measured**, on a labelled sample, against a threshold someone agrees to |

The spec should never claim the second as if it were the first. A bank's
reviewer will read "masks CID" as "no CID leaves", and NER recall is never 100%.
The honest wording is: *every detected value is masked everywhere, nothing
unmaskable is sent, and detection recall on the agreed sample is ≥ X*.

## 2. Where document text leaves the machine today

Every path a masked pipeline must cover. Found by reading the code at `1bfb544`.

| # | Egress | What it receives | Built at |
|---|---|---|---|
| E1 | Stage model call (`run`, a try, `--replay` asks nothing) | each input's converted text, wrapped as `<document key="...">` (R3.13); `reference` text (R3.18); earlier steps' answers | `RunInputs.document_content` / `reference_content`, `src/dossier/cli/run.py:536`; rendered by `_input_values`, `src/dossier/application/run.py:1379`; key in the wrapper at `run.py:1503` |
| E2 | Stage model call with **page images** (`per_part`, `documents@page_images`) | PNG pages: the CID is in the pixels | `RunInputs.document_parts` |
| E3 | Judge call (`eval`, `calibrate`) | rubric, the document's text, the candidate answer; parts when the step read pages | `judge_prompt`, `src/dossier/application/eval.py:633`; text from `replayed_inputs`, `run.py:1700` |
| E4 | Embedding call (`embed`) | body chunks of the converted text, the record chunk of free-text answers | `cli/embed.py:111` (`ToIndex.text`), `application/embed.py` |
| E5 | Embedding call (`search`) | the query a person typed | `application/search.py` |
| E6 | pgvector rows | `title` (taken from the text, `embed.py:245`), chunk `text`, `text_search`, `heading_path`, `filter_values`, `key`, `document_id` | `infrastructure/index/postgres.py` |
| E7 | MLflow traces | under `capture: full`, every span's inputs and outputs: the rendered prompt values and replies (`domain/tracking.py:1138`); the search query | `infrastructure/tracking/` |
| E8 | MLflow other records | document keys (sync's `changes.json`, spans named per document), gold expectations published as a dataset (spec 012), answers sent for review (spec 015) | specs 011, 012, 015 |

One seam covers most of them. `replayed_inputs` is how `eval`, `embed`, `gc` and
`--replay` all read "the text a run read", and `RunInputs` is how a run reads it.
If both serve the **masked** text, E1, E3, E4, E6 and E7 follow without a second
call site. E2, E5, E8 and the keys need their own decisions (D5, D6, D9, D10).

## 3. The design proposed

### 3.1 One seam: the masked view

```
 sync ─▶ store ┃ convert ─▶ [mask] ─▶ stages ─▶ eval / calibrate
               ┃     │         │
               ┃     │         └─▶ embed ─▶ pgvector     search (query masked too)
               ┃     └─ unmasked artifact stays in the cache, for unmasked pipelines
```

The masked view is a **derived artifact**, cached in `.dossier/cache/` like a
conversion, with a provenance record (R0.3):

```
K_mask = H( converted_artifact_hash + masker_id + masker_version + masking_declaration_hash )
```

- A pipeline that does not declare masking never computes one. Nothing about
  today's keys, manifests or runs moves (this is a rule: the default changes nothing).
- A pipeline that declares it reads the masked view everywhere it read the
  converted text: its stage inputs, its `reference`, its grounding (R6.4 checks
  a quote against the text the model was shown, which is the masked text), its
  judges, its index.
- The masked view's hash is what enters `K_stage` as the input artifact hash,
  so turning masking on re-runs every step, and changing a recogniser re-runs
  exactly the documents whose masked text changed.
- The manifest pins the masker (id, version, declaration hash), as it pins
  converters (R8.9), so `--replay`, `eval`, `embed` and `gc` recompose `K_mask`
  from the manifest alone and never re-mask with whatever is installed today
  (R4.7's rule, applied to masking).

### 3.2 The declaration

One key in `pipeline.yaml`. Absent means off.

```yaml
# pipelines/incident-audit/pipeline.yaml
sources:   [incidents-jira, incidents-manual]
reference: [procedures-confluence]
model:     gemini:gemini-3.5-flash-lite
masking:   masking/cid.yaml          # absent: no masking (the default)
steps: ...
```

What is masked is declared in its own file, beside the prompts, and its hash
enters every key (R0.5):

```yaml
# pipelines/incident-audit/masking/cid.yaml
masker: presidio
languages: [en, de]
score_threshold: OPEN            # never invented; measured (D12)
entities:
  - PERSON
  - EMAIL_ADDRESS
  - PHONE_NUMBER
  - IBAN_CODE
  - CREDIT_CARD
  - CH_AHV                       # declared below
  - CLIENT_NUMBER                # declared below
patterns:
  CH_AHV:        {regex: '\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b', checksum: ean13}
  CLIENT_NUMBER: {regex: OPEN}   # the bank's format, from the user
allow: [masking/allow.txt]       # never masked: systems, vendors, sites
deny_env: DOSSIER_CID_DENYLIST   # optional: a local file of client names, never committed
```

A deny-list of known client names is the most reliable recogniser a bank has,
and is itself CID: it lives outside the repository, named by an environment
variable (R1.8's pattern), and only its hash enters a key.

### 3.3 Presidio's part, and `dossier`'s part

Presidio **detects**. `dossier` **decides**. This keeps the decision in `domain/`,
where it can be mutation-tested (CLAUDE.md, "Default to `domain/`").

| Part | Where | Why there |
|---|---|---|
| Find candidate spans: NER per language, pattern recognisers, deny-list, with scores | `infrastructure/maskers/presidio.py`, registered as `dossier.maskers` entry point `presidio` | wiring around a heavy library and its models |
| Drop spans under the threshold, drop allow-listed ones, resolve overlaps (longest, then highest score, then earliest) | `domain/masking.py` | a decision over a list of spans: a plain dict, no fixtures |
| Number placeholders by first occurrence, the same surface form getting the same number | `domain/masking.py` | deterministic, and the thing a reviewer most needs to trust |
| Write the masked text | `domain/masking.py` | pure string work |
| The `Masker` port: `spans(text, languages) -> list[Span]` | `domain/ports.py` | so the suite runs a `FakeMasker` (pattern-only) offline, and counts its calls |

`presidio-anonymizer` is not needed: replacing spans is the domain's job, and
doing it ourselves keeps the output a function we can prove.

Placeholder form, proposed: `[PERSON_1]`, `[CLIENT_NUMBER_2]`. Square brackets,
not angle brackets, because prompts already wrap documents in
`<document key="...">` tags (R3.13), and `<PERSON>` reads to a model as another tag.

### 3.4 Fail closed

With masking declared, anything that cannot be masked is refused, never sent:

| Situation | Outcome |
|---|---|
| no masker installed for the declared `masker:`, or its language model is missing | the run stops before any call, naming the command that installs it (R8.15's shape) |
| a step reads `page_images`, or a judge would be shown parts | refused at load time, naming the step (D5) |
| masking fails on one document | that document fails, named; the rest run (R8.6's shape). It is never sent unmasked |
| an unknown entity name, an undeclared pattern, `score_threshold` missing | refused at load time (R3.1's shape) |
| a document key in which the masker finds CID | that document fails, naming the key (D6) |

### 3.5 Embed and search

The index declares `pipeline:`, so it inherits the pipeline's masking. It has
no switch of its own.

- Body chunks are cut from the masked text, so `title`, `heading_path`, `text`
  and `text_search` hold masked text.
- The record chunk is built from answers a masked run gave. It is masked once
  more before it is written (masking is idempotent: masking masked text changes
  nothing, which is a rule). A run made before masking was declared read a
  different view, and its record is not carried (R18.8's rule, extended).
- `content_hash` covers the masking, so declaring it rewrites every row.
- The query of `dossier search` is masked by the same masker before it is
  embedded, searched or recorded.

### 3.6 Eval, calibrate and gold

A judge is shown the masked text (it comes through `replayed_inputs`). A gold
value or a calibration candidate shown to a judge, or compared by a scorer, is
masked with **its document's** numbering, so `Erika Mustermann` is `[PERSON_1]`
in the document, the answer and the gold value alike. Categories are unaffected:
an enum value is never CID.

### 3.7 MLflow

Under `capture: full`, traces already record exactly what was sent, so they
carry masked text by construction. What a masked pipeline still has to cover:
gold expectations published as a dataset (spec 012), the search query, and the
keys (D6). A masked run records, per entity type, **how many** values it masked:
counts, never the values. That makes masking visible in MLflow (spec 011).

### 3.8 Seeing it before a call

Spec 008's `dossier convert` exists so the text a stage will see can be read
before any call. With masking declared, `dossier convert <pipeline>` also builds
the masked views and prints what it masked, per source and entity type. Reading
one document's masked text locally is part of the same slice.

## 4. Decisions for `/discover`

Each one has a recommendation. The ones marked **(blocking)** need the user;
`/discover` can settle the rest with the recommendation unless the user objects.

**D1 — What counts as CID (blocking).**
*Recommend:* a declared list per pipeline (§3.2). Start with PERSON, EMAIL_ADDRESS,
PHONE_NUMBER, IBAN_CODE, CREDIT_CARD, CH_AHV, CLIENT_NUMBER, plus the optional
deny-list. Leave ORGANIZATION and LOCATION out by default and allow them per
pipeline.
*For:* incident text is full of vendors, systems and sites ("Oracle", "Zurich
DC2"). Masking every organisation destroys the root causes the pipeline exists to
extract, and spaCy's ORG label is noisy.
*Against:* a client company that is not on the deny-list and is named only as
an organisation is not masked.
*Alternatives:* everything Presidio knows (more recall, much less signal); patterns
only (precise, misses names).
*Needed from the user:* the client and account number formats, and whether a
client-name list exists that can be exported locally.

**D2 — The detection engine.**
*Recommend:* `presidio-analyzer` (2.2.364, 2026-07-22, MIT, Python <3.15) with
spaCy `en_core_web_lg` and `de_core_news_lg`, pinned exactly in a new `masking`
extra.
*For:* mature; its pattern recognisers, checksums and context words cover the
number-shaped CID; the NER models run on the CPU.
*Against:* it depends on spaCy and `tldextract` (see the spike, §7), and on
spaCy model wheels that must be pinned like Docling's weights.
*Alternatives:* Presidio's `gliner` extra, a multilingual PII model on
`onnxruntime` (already in the lock through Docling): better recall on names,
weights from Hugging Face that must be pinned locally. A local LLM through
Ollama: rejected, because it is not deterministic, so it cannot sit under a key.
Regex only: misses names.

**D3 — The placeholder and its scope (blocking).**
*Recommend:* `[PERSON_1]`, numbered within a document.
*For:* deterministic, no secret, keeps "two different people" readable to the model.
*Against:* `[PERSON_1]` in `INC-4821` and in `INC-4822` are unrelated people,
which an `aggregate` or `per_group` step could conflate, and "the same client in
three incidents" is no longer visible.
*Alternatives:* type only, `[PERSON]` (loses who is who); a keyed pseudonym,
`[CLIENT_3f9a1c]`, an HMAC under a local secret (links across documents, but
needs key management, and the key's fingerprint enters `K_mask`); reversible
encryption (long ciphertext the model cannot use).

**D4 — Where masking sits.**
*Recommend:* the cached masked view (§3.1).
*For:* one seam, read by every consumer through `RunInputs` and `replayed_inputs`;
keyed, replayable, and kept by `gc`.
*Against:* one more cache entry per (document, masking declaration).
*Alternative:* mask at prompt rendering and again at chunking. Two call sites,
plus judges, plus replay, and each one is a place a missed path ships CID.

**D5 — Page images.**
*Recommend:* in a masked pipeline, any step reading `page_images` is refused at
load. A scanned PDF reaches a masked pipeline as text, through `docling-markdown`'s
OCR (R8.14), which is then masked.
*For:* fail closed; image redaction is a project of its own.
*Against:* the picture-only steps (INC-5720, exercise 10's `per_part`) cannot
run masked.
*Later:* redact pixels using OCR boxes (Presidio's image redactor uses Tesseract,
a system binary; Docling's RapidOCR is already pinned).

**D6 — Document keys.**
A key reaches the model (`<document key="...">`), the index (`key`,
`document_id`) and MLflow (span names). A folder file named after a client puts
the client's name in all three.
*Recommend:* the masker reads each key too. In a masked pipeline, a document
whose key holds CID fails, naming it, and the fix is renaming at the source.
*For:* simple, fail closed, no change to R3.13, R6.3 or R6.4.
*Against:* one more reason a document can fail.
*Alternative:* show the model an alias (`doc-1`) and map it back for grounding.
That rewrites the key contract of three specs.

**D7 — Gold, judges and calibration.**
*Recommend:* §3.6: gold values and candidates are masked with their document's
numbering wherever a judge sees them or a scorer compares them.
*Alternative:* write a masked pipeline's gold against the masked text. That
means re-authoring gold, and gold would have to change whenever the recognisers did.

**D8 — The mapping from placeholder to value.**
*Recommend:* keep it in the masked view's sidecar in `.dossier/cache/`: local,
the same exposure as the snapshots, never in `runs/`, never sent anywhere. It is
what D7 masks gold with, and what a later local `--unmask` view reads.
*Alternative:* keep no mapping, and re-run the masker whenever one is needed.
Slower, and still the same values on the same disk.

**D9 — An index built before masking was declared.**
Deleted rows stay in Postgres's WAL, its dead tuples and its backups.
*Recommend:* the index records whether it is masked. Switching an existing index
from unmasked to masked stops, with the reason, and asks for a fresh index (a new
database, or drop and rebuild).
*Alternative:* rewrite in place and warn. That is cheaper, and it leaves CID in
history that nobody sees.

**D10 — MLflow's scope (blocking).**
*Recommend:* in scope: the MLflow server is shared and authenticated, so it is
not this machine. Traces are covered by construction (§3.7), datasets publish
masked expectations, and the search query is masked.
*Alternative:* declare MLflow a trusted sink and cover only OpenWebUI and pgvector,
as the request names. That is cheaper, and the trace of a masked run still
shows the masked prompt, which is most of it anyway.

**D11 — Languages.**
*Recommend:* a declared list. Every document is analysed in each declared
language, and the spans are unioned.
*For:* deterministic, no language detector, and a German incident (INC-5699)
with English system names is covered by both models.
*Against:* the time per document scales with the number of languages.
*Alternative:* detect the language per document or chunk. One more dependency,
and a decision that can flip on mixed text.

**D12 — The score threshold.** OPEN, by CLAUDE.md's rule. It is a declared value in
`cid.yaml` and not a default `dossier` invents. It is measured on a labelled sample (D13).

**D13 — Measuring detection (blocking for the evaluated rule).**
*Recommend:* one `evaluated` rule, *recall of CID on the agreed sample ≥ X*,
`Threshold: OPEN`. Its committed half is a synthetic canary corpus (§5). Its real
half is a labelled sample of real incidents, kept outside the repository and run
deliberately (`-m live`), like Docling's tests.

**D14 — A source that demands masking.**
*Recommend:* an optional source key, `requires_masking: true`, default false.
Any pipeline that reads that source without `masking:` is refused at load.
*For:* masking stays opt-in per pipeline, as asked, but a sensitive source cannot
be audited by a pipeline that forgot to declare it. One load-time check.
*Alternative:* none, and rely on review of `pipeline.yaml`.

## 5. Draft rules

These are candidates. `/discover` numbers them, writes their example tables from
`specs/_fixtures.md`, and splits or merges them.

**Spec 020, CID masking (new):**

1. *(acceptance)* With `masking:` declared, `dossier run`, `dossier embed` and
   `dossier search` over the canary corpus send no canary value to any model
   call, write none to the index, and record none to MLflow. *Counter-example:*
   without `masking:`, the same commands send them unchanged. This is the outer
   loop. `FakeModelClient` already records what it was asked.
2. A pipeline that does not declare `masking:` resolves to a byte-identical
   manifest and identical keys to today's (R0.4). Declaring it is the only thing
   that moves them.
3. A detected span is replaced by `[TYPE_n]`, numbered by first occurrence in its
   document, and the same surface form gets the same number.
4. Overlapping spans resolve to one, by length, then score, then position. An
   allow-listed span is never masked.
5. Masking masked text changes nothing (idempotence).
6. The masked view is keyed by `K_mask` and cached with a provenance record. Changing
   the declaration, the masker version or the converted text re-masks, and nothing else does.
7. A masked run's manifest pins the masker. `--replay`, `eval`, `embed` and `gc` read the
   masked view through it, and never re-mask with what is installed.
8. With masking declared, a missing masker or language model stops the run
   before any call, naming the install command, and no model is downloaded.
9. With masking declared, a step reading `page_images` is refused at load.
10. A document whose masking fails, or whose key holds CID, fails alone, and is never sent.
11. The masker reaches no network. With sockets blocked it masks a document (`live`).
12. *(evaluated)* Recall of CID on the agreed sample is ≥ OPEN.

**Amendments (new rules at the end of their spec, ids never moved):**

| Spec | New rule, roughly |
|---|---|
| 003 | `masking:` is optional, names a declaration that loads and validates, and an unknown entity is refused at load |
| 001 / 003 | `requires_masking: true` on a source refuses any pipeline reading it without `masking:` (D14) |
| 004 | `--plan` shows the masker and which documents would be re-masked |
| 005 | `K_mask` composition; a masked input's hash is what enters `K_stage` |
| 007 | a judge is shown masked evidence, and gold values are masked with their document's numbering |
| 011 | a masked run records how many values it masked per entity type, never the values |
| 012 | a masked pipeline's gold set publishes masked expectations |
| 016 | `gc` keeps the masked views a kept run needs |
| 017 | `dossier status` says whether each pipeline masks |
| 018 | an index of a masked pipeline holds masked text only; its record comes only from a run that read the same masked view; switching an index to masked stops (D9) |
| 019 | a search over a masked index masks its query before embedding, searching or recording it |

**Fixtures** (`specs/_fixtures.md`, a new section *Client identifying data*). All
of these are fictional, and are chosen so a test can grep for them:

| Value | Type |
|---|---|
| `Erika Mustermann`, `Hans Muster` | PERSON |
| `erika.mustermann@example.ch` | EMAIL_ADDRESS |
| `+41 44 555 01 23` | PHONE_NUMBER |
| `CH93 0076 2011 6238 5295 7` | IBAN_CODE (the published sample IBAN) |
| `756.1234.5678.97` | CH_AHV (the published sample number) |
| a client number in the bank's format | CLIENT_NUMBER, pending D1 |

The canary corpus is two or three of the existing incidents (INC-4821 and
INC-5699, which is German) with these values added, as new keys so that no
existing fixture changes.

## 6. Slices, one PR each

| # | Slice | Proves |
|---|---|---|
| 0 | **Spike**, no PR: §7 on this machine | that the engine choice survives contact |
| 1 | `/discover`: spec 020 and the amendments, in one spec commit | — |
| 2 | `/accept`: rule 1, red | the outer loop |
| 3 | `domain/masking.py`: spans to masked text, numbering, overlaps, idempotence; the `Masker` port and a `FakeMasker` | rules 3–5, mutation-tested |
| 4 | config: `masking:`, `cid.yaml`, `requires_masking`, the refusals at load | amendments 003 and 001, rule 9 |
| 5 | the masked view: `K_mask`, cache, provenance, manifest pin; `run` reads it; `--plan` shows it | rules 2, 6, 7, 10 |
| 6 | `replayed_inputs` reads the masked view: `eval`, `calibrate`, gold masking, `gc` | amendments 007, 016 |
| 7 | `embed` and `search` | amendments 018, 019 |
| 8 | the Presidio masker, the `masking` extra, `live` tests, no downloads | rules 8, 11 |
| 9 | MLflow counts, masked datasets, `status` | amendments 011, 012, 017; rule 1 goes green |
| 10 | live check against the real OpenWebUI and the dev pgvector, then docs, `docs/history/slices.md`, and playground exercise 22 | "a fake is a claim" |

Slice 10's live check reads what actually arrived: the prompts OpenWebUI holds,
if it keeps them, the rows in `dossier_index.chunks`, and the MLflow traces,
each grepped for every canary value.

## 7. The spike: check before writing rules

Run once, in a worktree venv (`uv sync --locked --all-extras --no-extra docling`, then add the candidates):

- [ ] `presidio-analyzer`, spaCy and the `en_core_web_lg` and `de_core_news_lg` wheels install and load on this machine's Python 3.13 under Application Control. Check that spaCy has a `cp313-win_amd64` wheel at the pinned version, so nothing builds from source.
- [ ] **Does Presidio download a missing spaCy model when it loads?** If it does, `dossier` must load the pipeline itself and hand it over, or check that it is installed first (rule 8).
- [ ] **Does `tldextract` fetch the public suffix list on first use?** Presidio's e-mail and URL recognisers use it. It must be made offline (its bundled snapshot, `suffix_list_urls=()`), or R0.17's promise is broken by a dependency the `ast` walk cannot see.
- [ ] The same document gives byte-identical masked text on Windows and in `python:3.12-slim` in Docker. spaCy's NER runs on floats, so check rather than assume.
- [ ] Time and memory per document on the PDF postmortem corpus. Two `lg` models are about 1 GB of RAM, which matters on this machine.
- [ ] Recall and noise on INC-5699 (German) and on two or three Jira-shaped fixtures with canaries added. This decides D1's default entities and gives D12 a starting number to argue about.
- [ ] GLiNER through Presidio's `gliner` extra on the same documents, so that D2 is decided by evidence.

## 8. Risks and limits

- **Recall.** Statistical NER misses names: unusual ones, ones in lower case, ones
  in tables, ones split across a converted line break. The deny-list and the
  pattern recognisers carry the CID that matters most. The rest is measured
  (D13), not promised.
- **Signal loss.** Every false positive removes a word the model needed. ORG and
  LOCATION are the worst offenders, which is why they are off by default (D1).
- **Cross-document reasoning** suffers under per-document numbering (D3).
- **History.** Masking applies from when it is declared. It does not clean an
  index built before (D9), MLflow traces already recorded, or OpenWebUI's own logs.
- **Cost.** Turning masking on re-runs every step of the pipeline and re-embeds
  its index, once.
- **Images.** No masked pipeline can read pictures until pixel redaction exists (D5).

## 9. Out of scope for the first spec

- Masking pixels (D5).
- A local `--unmask` view of a run's answers (D8 keeps it possible).
- Keyed pseudonyms that link one client across documents (D3's alternative).
- Masking at sync time, or in the snapshot store. Fetching stays unmasked, as asked.
- Per-item permissions in the index (spec 018 left these out; masking does not replace them).
