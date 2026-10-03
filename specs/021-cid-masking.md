# 021 — Masking client identifying data

**Status:** Partially implemented
**Rules:** R21.1 – R21.14

## Purpose

The incidents `dossier` audits name clients: who called, which account, which
IBAN. A pipeline sends their text to a model through OpenWebUI, and `embed`
writes it to an index other systems read. Neither has a reason to see a
client's name: a root cause is the same root cause whoever it happened to.

This spec lets a pipeline declare **CID masking** — CID being *client
identifying data*. Declared, every text the pipeline shows a model is first
masked on this machine: a client's name becomes `[PERSON_1]`, an IBAN
`[IBAN_CODE_1]`. It is off unless declared, and declaring it changes nothing
before conversion: documents are fetched, frozen and converted exactly as
they are, so the snapshot stays the evidence and a pipeline that does not
mask reads what it always read.

This first part covers what a run, a try and an eval's judges show a model
(R21.1 – R21.8), and the masker that finds the values, Presidio (R21.9 –
R21.14). The index, search, calibration, gold and the rest of MLflow are
later parts of this spec (see "Later").

## What masking promises, and what it does not

Two claims, kept apart on purpose:

| Claim | Kind | Proved |
|---|---|---|
| **The mechanism.** Every value the masker detects is replaced in everything a masked pipeline shows a model, and anything that cannot be masked is refused rather than sent | deterministic | with `==`, offline, against a fake masker (R21.1 – R21.8) |
| **The detection.** The masker finds the client data in real incidents | evaluated | measured on a labelled sample against an agreed threshold (R21.14). Named-entity recognition is statistical, and its recall is never 100% |

A reviewer reading "masks CID" will hear "no CID leaves". What this spec
supports is narrower and true: every detected value is masked everywhere,
nothing unmaskable is sent, and recall on the agreed sample is measured.

## The declaration

One key in `pipeline.yaml`. Absent, nothing is masked:

```yaml
# pipelines/incident-audit/pipeline.yaml
sources:   [incidents-jira, incidents-manual]
reference: [procedures-confluence]
model:     gemini:gemini-3.5-flash-lite
masking:   masking/cid.yaml
steps: ...
```

What is masked is declared in its own file beside the prompts, as an `output`
is:

```yaml
# pipelines/incident-audit/masking/cid.yaml
masker: presidio
languages: [en, de, fr, it]
score_threshold: 0.5
entities: [PERSON, EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE, CREDIT_CARD, CH_AHV, CLIENT_NUMBER]
patterns:
  CH_AHV:        {regex: '\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b', score: 0.5, context: [ahv, avs]}
  CLIENT_NUMBER: {regex: '\bCIF \d{4}-\d{6}\b', score: 0.85}
allow: masking/allow.txt          # never masked: systems, vendors, sites
```

- **`score_threshold`** is required and has no default. Presidio scores a
  detection with a constant per recogniser -- a name 0.85, an IBAN or an e-mail
  1.0, a phone number 0.4, or 0.75 beside a word such as `phone` -- so the
  threshold decides which recognisers count. That is the pipeline author's
  decision, not `dossier`'s.
- **`entities`** names what is masked. A detection of a type not named is kept
  as written. `ORGANIZATION` and `LOCATION` can be named. They are not here,
  because incidents are full of vendors, systems and sites, and masking
  "Oracle" or "Zurich DC2" removes the root cause the pipeline exists to find.
- **`patterns`** declares recognisers of the pipeline's own, such as the
  bank's client number. The pattern above is the fixtures' fictional one.
- **`allow`** names a file of values that are never masked.

The declaration's text, and the text of every file it names, enter the
masked view's key (R21.5).

## What masked text looks like

```
Erika Mustermann called about CH93 0076 2011 6238 5295 7. Hans Muster confirmed. Erika Mustermann agreed.
[PERSON_1] called about [IBAN_CODE_1]. [PERSON_2] confirmed. [PERSON_1] agreed.
```

- **Numbered by first appearance, per type, per document** (R21.2). The same
  value -- compared after case folding and collapsing whitespace -- always gets
  the same number, so the model can still tell two people apart and follow
  one through a document.
- **Scoped to its document.** `[PERSON_1]` in `INC-4821` and in `INC-4822` are
  unrelated. A keyed pseudonym that follows one client across documents was
  considered and left out: it needs a secret, and a secret's fingerprint in
  every key (decided 2026-10-02).
- **Square brackets**, because prompts already wrap each document in
  `<document key="...">` (R3.13), and `<PERSON>` reads to a model as one more tag.
- **Overlaps are masked as one** (R21.3). Presidio finds `example.ch` as a URL
  inside `erika.mustermann@example.ch`, and masking both would leave
  half an address between two placeholders.

## The masked view

```
 sync ─▶ store ┃ convert ─▶ [mask] ─▶ stages ─▶ eval's judges
               ┃     │
               ┃     └─ the converted text stays in the cache, for a pipeline that does not mask
```

The masked view is an artifact derived from a converted one, written with a
provenance record (R0.3), and cached in a namespace of its own:

```
K_mask = H( converted_text_hash + masker_id + masker_version
            + MASKING_VERSION + declaration_hash )
```

- **`MASKING_VERSION`** is the version of `dossier`'s own masking rules: the
  numbering, the overlaps, the language vote (R21.9). It is raised whenever
  those could write different text for the same input, as a converter's version
  is (R5.4).
- **`declaration_hash`** covers `cid.yaml` and every file it names.
- **The provenance record** names the inputs, the language the document was
  read in, and how many values of each type were masked. It never names a value.

A pipeline that declares masking reads the masked view wherever it read the
converted text: its documents, its `reference`, and so its grounding. R6.4
finds a quote in the text the model was shown, which is the masked text. Its
answers under `runs/` hold placeholders.

Earlier steps' answers are not masked again: they were made from masked text.

The manifest pins the masker, as it pins converters (R8.9). `--replay` and
`eval` therefore recompose `K_mask` from the manifest alone, and never re-mask
with what is installed today (R21.6).

`gc` does not collect the masked view's namespace, as it does not collect the
judge cache (R16.3 row 6). A masked view is small text, and a kept run
replayed after a `gc` must find it.

Every place `dossier` reads a document's text for a model goes through one of
two functions: `RunInputs`, built by `dossier run`, and `replayed_inputs`, read
by `--replay`, `eval`, `embed` and `gc`. Masking is applied there and nowhere
else, so that no path to a model is missed by being a second call site.

## Refused rather than sent

| Situation | Outcome | Rule |
|---|---|---|
| a step reads `page_images` | refused at load: the CID is in the pixels, and nothing here masks pixels | R21.7 |
| the declared masker is not installed, or a declared language's model is missing | refused before any call, naming what installs it | R21.7, R21.10 |
| `cid.yaml` with no `score_threshold`, or naming an entity nothing recognises | refused at load, naming the file and the key (R3.1) | R21.7 |
| the masker fails on one document | that document fails, named, and the rest run (R8.6) | R21.8 |
| a document's key holds a detected value | that document fails, naming the key, and is never sent | R21.8 |

## The Presidio masker

`presidio`, registered in the `dossier.maskers` entry-point group, as a
converter is (R8.7). It wraps Presidio's analyzer, which finds candidate
spans; everything after that is a decision in `dossier.domain.masking`. That
covers the threshold, the allow-list, overlaps, numbering and the text
written. `presidio-anonymizer` is not used.

- **One language per document**, chosen by a pure function: the declared
  language whose common function words the document uses most (R21.9).
  Analysing in every language and joining the results was measured and
  rejected. The English model, reading the German `INC-5699`, found 26 names
  that are not names, and the German model, reading English, missed the
  canaries' names.
- **No download, ever** (R21.10). A plain `AnalyzerEngine()`, or a model name
  with a typo, makes Presidio run `spacy.cli.download`, which fetches and then
  installs with `pip` in a subprocess. The masker loads each model itself with
  `spacy.load`, only after checking that the model is installed, and hands
  Presidio the loaded pipeline.
- **No network** (R21.11). Presidio's e-mail recogniser asks `tldextract`,
  which fetches the public suffix list from `publicsuffix.org` on a machine
  that has never fetched it, and caches whichever list it got. The masker
  gives it its bundled list and no URL. R0.19's import walk cannot see either
  of these, because both are inside the libraries. That is why they are rules
  here, as Docling's model folder is (R8.15).
- **Pinned.** `presidio-analyzer` 2.2.364, spaCy 3.8.16, and the model wheels
  `en_core_web_lg`, `de_core_news_lg`, `fr_core_news_lg` and `it_core_news_lg`
  3.8.0, by hash, in a `masking` extra. The masker's version names them all:
  moving a pin raises it. A model is loaded only when a document is read in its
  language, so a corpus in English and German loads two, about 1.6 GB.
- **The same bytes on every machine** (R21.13). Measured on 2026-10-02:
  - Presidio's scores are constants, not computed floats.
  - The spans found were byte-identical across processes, across hash seeds,
    and in `python:3.12-slim` and `python:3.13-slim`.
  - The masked view's hash enters every stage key, so R0.4 needs this, and the
    canaries' masked bytes are pinned.

Measured on this machine on 2026-10-02:
- Loading English and German takes 4 to 7 s.
- A 3,000 to 7,000-character document takes 0.2 to 0.5 s.
- The masked view is cached, so a document is masked once per declaration.

## Decisions

Decided by `a.aleks` on 2026-10-02:

- **CID is client identifying data:**
  - names, e-mail, phone, IBAN and card, AHV number, and the client number;
  - `ORGANIZATION` and `LOCATION` are opt-in.
- **Placeholders** are `[TYPE_n]`, numbered within a document.
- **MLflow is in scope:**
  - A masked pipeline records no CID to MLflow. In this part that holds by
    construction, because a trace records what was sent (R21.1 row 3).
  - Datasets, review and search follow in later parts.
- **Languages are English, German, French and Italian:**
  - One language is chosen per document, by a function-word vote.
  - The alternatives were `lingua-language-detector`, every language joined,
    and a language declared per source.
- **Presidio with spaCy's `lg` models.** See "Existing options considered".
- **`score_threshold` is required per pipeline**, and `dossier` ships no number.
- **Detection recall on real incidents is OPEN** until a labelled sample exists
  (R21.14). The synthetic canaries are a deterministic test instead (R21.12).

## Existing options considered

Checked on PyPI on 2026-10-02, and measured on this machine the same day, in a
spike kept outside the repository:

| Option | Covers | Left to `dossier` | Verdict |
|---|---|---|---|
| **Presidio** (`presidio-analyzer` 2.2.364, 2026-07-22, MIT) with spaCy 3.8.16 `*_core_news_lg` / `en_core_web_lg` 3.8.0 | named entities in four languages; pattern recognisers with checksums and context words; IBAN, e-mail, phone, card out of the box. Wheels for cp313 on Windows; identical spans on Windows and Linux | where masking sits, the key, the numbering, refusing what cannot be masked, the language choice, and the two network paths it opens by default | **Chosen** |
| Presidio with GLiNER (`gliner` 0.2.29, 2026-09-08, Apache-2.0; `urchade/gliner_multi_pii-v1`) | found names and the client number better | needs torch, 4.1 GB of memory, and 4 to 12 s a document, against Presidio's 0.2 to 0.5 s; missed every IBAN; its determinism across machines is untested; weights from Hugging Face to pin | Rejected for now. It can be a second masker later, registered by entry point |
| Patterns only | IBAN, AHV, e-mail, phone, client number, exactly | finds no name it is not given | Rejected as the only engine. Kept as Presidio's pattern recognisers |
| `scrubadub` 2.0.1 | names and contacts | its last release was 2023-09 | Rejected: not maintained |
| A local model through Ollama | anything it is asked to find | an answer that is not reproducible, so a masked view could not be keyed | Rejected |

## Later

These are later parts of this spec, and are not built by R21.1 – R21.14:

- **The index and search.** `embed` reads the masked view, and its record chunk
  is masked again. Masking masked text changes nothing. An index switching to
  masked stops, because Postgres keeps deleted rows in its WAL and backups. A
  search's query is masked before it is embedded, searched or recorded.
- **Calibration and gold.** A gold value or a calibration candidate shown to a
  judge is masked with its own document's numbering.
- **The rest of MLflow.**
  - A gold set publishes masked expectations.
  - A run records how many values of each type it masked.
- **`dossier status`, and a source that demands masking.** That is a
  `requires_masking: true` source refusing any pipeline that reads it unmasked.
- **Seeing it first.** `dossier convert` reports what it masked, and one
  document's masked text can be read locally.
- **Pixels, and unmasking.** Redacting page images, and a local view of a run's
  answers with the values put back.

Not covered by masking at all:

- **Keys.** A document key reaches MLflow when it is synced (R11.6), before any
  pipeline masks anything. R21.8 keeps a key holding client data away from the
  model; renaming at the source keeps it out of the rest.
- **What was sent before masking was declared.** That includes traces already
  recorded and OpenWebUI's own logs.

## Must hold

### R21.1 — a masked pipeline's run and eval show no model a value its masker detects

The acceptance rule of the first part. Every prompt a run, a try and an eval's
judges send -- documents, `reference` and judge evidence alike -- holds the
placeholder where the converted text held the value.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.run`, `dossier.cli.eval`)
- **Proved by:** `tests/acceptance/test_R021_1__a_masked_pipeline_shows_no_model_client_data.py`
- **Status:** IN PROGRESS

| # | Given | Then |
|---|-------|------|
| 1 | `masking:` declared, `PLAY-6001` holding `Erika Mustermann` and `CH93 0076 2011 6238 5295 7` | `dossier run` then `dossier eval`: no prompt the fake model was sent holds either value; they hold `[PERSON_1]` and `[IBAN_CODE_1]` |
| 2 | the same, and `OPS-114` (reference) holding `Hans Muster` | no prompt holds `Hans Muster`; the procedure is masked as the documents are |
| 3 | the same, recorded under `capture: full` | no span the tracker was handed holds a canary: a trace records what was sent |
| 4 | *counter-example* — the same pipeline, no `masking:` | the prompts hold `Erika Mustermann` exactly as converted, and the masker is asked 0 times |

### R21.2 — a masked value becomes `[TYPE_n]`, numbered by first appearance in its document, and the same value always gets the same number

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.masking.masked`)
- **Proved by:** `tests/unit/test_R021_2__a_value_becomes_a_numbered_placeholder.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `Erika Mustermann called. Hans Muster confirmed. Erika Mustermann agreed.` | `[PERSON_1] called. [PERSON_2] confirmed. [PERSON_1] agreed.` |
| 2 | `Erika Mustermann`, then later `ERIKA  MUSTERMANN` in a heading | both `[PERSON_1]`: compared after case folding and collapsing whitespace |
| 3 | `Erika Mustermann` and `CH93 0076 2011 6238 5295 7` | `[PERSON_1]` and `[IBAN_CODE_1]`: numbered per type |
| 4 | `Erika Mustermann`, then `Mustermann` alone | `[PERSON_1]`, then `[PERSON_2]`: a different string is a different value, and no surname is guessed at |
| 5 | *counter-example* — `PLAY-6001` names `Hans Muster` first, `PLAY-6002` names `Erika Mustermann` first | both are `[PERSON_1]` in their own document: numbering is per document |

### R21.3 — overlapping detections are masked as one span covering both, under the longer one's type

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.masking.merged`)
- **Proved by:** `tests/unit/test_R021_3__overlapping_detections_are_masked_as_one.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | EMAIL_ADDRESS over `erika.mustermann@example.ch`, URL over `example.ch` inside it | one `[EMAIL_ADDRESS_1]`; no fragment of the address is left between placeholders |
| 2 | `Hans Muster AG`: PERSON over `Hans Muster` (0–11), ORGANIZATION over `Muster AG` (5–14) | one span 0–14, `[PERSON_1]`, the longer's type; the span covers both, because masking more is the safe side |
| 3 | two detections of equal length over the same span, PERSON 0.85 and LOCATION 0.85 | one span, the type first by name, `LOCATION`: a tie is broken by something that never varies |
| 4 | *counter-example* — `Erika Mustermann` (0–16) and `Hans Muster` (21–32) | two placeholders: detections that only sit near each other stay apart |

### R21.4 — a detection is masked only when its type is declared, its score reaches the declared threshold, and its text is not allow-listed

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.masking.kept`)
- **Proved by:** `tests/unit/test_R021_4__a_detection_is_masked_only_when_declared_and_above_threshold.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `score_threshold: 0.5`, PERSON 0.85 over `Erika Mustermann` | masked |
| 2 | `score_threshold: 0.5`, PHONE_NUMBER 0.5 | masked: reaching the threshold is enough. The off-by-one row |
| 3 | `score_threshold: 0.5`, PHONE_NUMBER 0.4 over `+41 44 555 01 23` in German text with no context word | kept as written |
| 4 | LOCATION 0.85 over `Zurich`, `LOCATION` not in `entities` | kept as written |
| 5 | *counter-example* — ORGANIZATION 0.85 over `Oracle`, `ORGANIZATION` declared, `Oracle` in `allow.txt` | kept as written: an allow-listed value is never masked, whatever its score |

### R21.5 — the masked view is keyed by the converted text, the masker's id and version, `MASKING_VERSION` and the declaration, and nothing else re-masks it

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys.mask_inputs`)
- **Proved by:** `tests/unit/test_R021_5__the_masked_view_key_holds_what_can_change_it.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `masking/allow.txt` gains `Oracle` | `PLAY-6001` is re-masked, and every stage key over it moves (R5.2) |
| 2 | the masker's version `1.0.0` becomes `1.1.0` | every masked view is re-masked |
| 3 | `masking:` declared in a pipeline that had none, over `PLAY-6001` and `INC-4821` | `PLAY-6001`'s masked view differs from its text, so every stage key over it moves, and the steps after it (R5.2). `INC-4821`, in which nothing is detected, keeps its stage keys: a stage key holds the text a model is shown, and that text did not change |
| 4 | `pdf-markdown` raises its version and `INC-4830` converts to the same text | the masked view is served from the cache, and the masker is asked 0 times: it is keyed by the text, not by who made it |
| 5 | *counter-example* — `prompts/02_verify.md` edited | 0 masker calls; `verify` re-runs over the same masked text |

### R21.6 — a masked run's manifest pins its masker, and a replay and an eval read the masked view through it

- **Kind:** deterministic
- **Layer:** application (`dossier.application.run.replayed_inputs`)
- **Proved by:** `tests/integration/test_R021_6__replay_and_eval_read_the_pinned_masked_view.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | a masked run, then `dossier eval` | the judge is shown the masked text the step was shown; the masker is asked 0 times |
| 2 | a masked run, then `--replay` after `cid.yaml` was edited | reproduces from the masked view the manifest pins; nothing is re-masked with today's declaration |
| 3 | a masked run whose masked view of `PLAY-6001` is gone | the replay stops naming `PLAY-6001` and its masked view; nothing is substituted (R4.7) |
| 4 | *counter-example* — a run of a pipeline with no `masking:` | its manifest has no `masker` key at all, and its bytes are what they were before this spec (R4.8) |

### R21.7 — a masked pipeline that cannot be masked is refused before any model call

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/integration/test_R021_7__an_unmaskable_pipeline_is_refused_before_any_call.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `masking:` declared, a step reading `documents@page_images` | exit 2 at load naming the step: pixels cannot be masked; 0 model calls |
| 2 | `masker: presidio` and no masker registered under that name | exit 2 naming the `masking` extra that installs it; 0 model calls |
| 3 | `cid.yaml` with no `score_threshold` | exit 2 naming the file and the key (R3.1); 0 model calls |
| 4 | `entities: [CLIENT_ID]`, which no recogniser or pattern provides | exit 2 naming `CLIENT_ID`: a type nothing finds is a type silently left unmasked |
| 5 | *counter-example* — the same `documents@page_images` step, no `masking:` | loads and runs as today |

### R21.8 — a document that cannot be masked fails alone, and no model is asked about it

- **Kind:** deterministic
- **Layer:** application (`dossier.application.masking`)
- **Proved by:** `tests/integration/test_R021_8__a_document_that_cannot_be_masked_fails_alone.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | the masker raises on `PLAY-6002` | `PLAY-6002` failed, named with the error; `PLAY-6001` runs; exit 1 (R8.6) |
| 2 | a folder document keyed `Erika-Mustermann-complaint.pdf` | fails naming its key: a key is shown to the model (R3.13), so a key holding a value is never sent; 0 calls about it |
| 3 | the masker raises on `OPS-114`, a reference document | left out of every call's context and named, as a reference document that did not convert is; exit 1 |
| 4 | *counter-example* — `INC-4821`, in which the masker detects nothing | sent as converted, its masked view equal to its text; nothing detected is not a failure |

### R21.9 — a document is read in the declared language whose function words it uses most

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.masking.language_of`)
- **Proved by:** `tests/unit/test_R021_9__a_document_is_read_in_its_majority_language.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-5699`, written in German, `languages: [en, de, fr, it]` | `de` |
| 2 | `INC-5102`, written in English | `en` |
| 3 | `PLAY-6002`, German prose naming English systems (`orders-api`, `Kafka`) | `de`: a document is read in its majority language |
| 4 | `PLAY-4004`, a CSV of keys and numbers, none of the four languages' words | `en`, the first declared language: a vote with no votes falls to the order the author wrote |
| 5 | *counter-example* — `languages: [en]`, `INC-5699` | `en`, uncounted: the vote is only among the declared languages |

### R21.10 — the `presidio` masker never fetches a model: one that is missing fails naming the command that installs it

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.maskers.presidio`)
- **Proved by:** `tests/unit/test_R021_10__presidio_never_fetches_a_model.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `languages: [en, it]`, `it_core_news_lg` not installed, a document read as `it` | the run stops naming `it_core_news_lg` 3.8.0 and the install command; `spacy.cli.download` is never called, and no socket is opened |
| 2 | `de_core_news_lg` installed at 3.7.1, where 3.8.0 is pinned | the same failure, naming the version expected and the one found |
| 3 | *counter-example* — `it_core_news_lg` missing, every document read as `en` or `de` | runs: a model is needed by a document read in its language, not by its name in the declaration |

### R21.11 — the `presidio` masker masks with every network connection refused

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.maskers.presidio`)
- **Proved by:** `tests/integration/test_R021_11__presidio_masks_with_the_network_blocked.py`
- **Status:** NOT MET

Marked `live`: it needs the models.

| # | Given | Then |
|---|-------|------|
| 1 | sockets blocked, `PLAY-6001` holding `erika.mustermann@example.ch` and a URL, an empty `tldextract` cache | masked; 0 connection attempts |
| 2 | the same, run twice | the same masked bytes: the bundled suffix list is used every time, and none is cached from the network |
| 3 | *counter-example* — Presidio's own default construction in the same process | not used: the masker never builds an engine that can call `spacy.cli.download` |

### R21.12 — a `dossier run` of the playground's masked pipeline with the `presidio` masker shows no model a canary

The acceptance rule of the second part, and the one that runs the real
masker. Marked `live`.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.run`)
- **Proved by:** `tests/acceptance/test_R021_12__presidio_masks_every_canary_before_the_model.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `PLAY-6001` – `PLAY-6004` (English, German, French, Italian), every canary in each | no prompt holds any canary; each document's provenance record names its language |
| 2 | `+41 44 555 01 23` beside `Telefon` in `PLAY-6002` | masked: the German context word lifts it to the threshold |
| 3 | `CIF 0042-118733` | masked as `CLIENT_NUMBER`, by the declared pattern; Presidio alone does not find it |
| 4 | *counter-example* — the username `k.oyelaran` in `PLAY-6001` | sent as written: an employee's username is not a declared type. What is not declared is not masked |

### R21.13 — the masked canaries are the same bytes on every machine

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.maskers.presidio`)
- **Proved by:** `tests/integration/test_R021_13__the_masked_canaries_are_the_same_bytes_everywhere.py`
- **Status:** NOT MET

Marked `live`. Their SHA-256s are pinned in the test, as a PNG part's are (R8.29).

| # | Given | Then |
|---|-------|------|
| 1 | `PLAY-6001` – `PLAY-6004` masked on Windows | the pinned SHA-256 of each masked view |
| 2 | the same in `python:3.12-slim` | the same four SHA-256s |
| 3 | the same, with a different `PYTHONHASHSEED` | the same four SHA-256s |
| 4 | *counter-example* — `en_core_web_lg` at another version | fails R21.10 before anything is masked: a different model is a different masker, never different bytes under the same key |

### R21.14 — the `presidio` masker detects the client data in the labelled sample of real incidents

- **Kind:** evaluated
- **Layer:** infrastructure (`dossier.infrastructure.maskers.presidio`)
- **Proved by:** `tests/evals/test_R021_14__cid_recall_on_the_labelled_sample.py`
- **Threshold:** OPEN — needs a labelled sample of real incidents, marked up on this machine and never committed; the number is `a.aleks`'s to agree once the sample exists
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | the labelled sample, every declared type marked by a person | recall per type, and over all, reported against the threshold |
| 2 | a value the sample marks and the masker misses | named by document and type, never by its text, in what the eval prints and records |
| 3 | *counter-example* — a detection the sample does not mark, such as a vendor read as a person | counted against precision, which is reported and not gated: a false positive costs signal, not privacy |

## Open questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | What recall makes masking good enough for real incidents? | OPEN — needs the labelled sample of R21.14; the number is `a.aleks`'s |
| 2 | The bank's client and account number formats | The pipeline author's, declared under `patterns:` in their own `cid.yaml`; the fixtures use the fictional `CIF 0042-118733` |
| 3 | Is a list of client names available to export locally as a deny-list? | Asked when the pilot starts: it would lift recall on names the models miss, and would itself be client data kept outside the repository |
