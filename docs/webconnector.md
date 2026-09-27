# A web connector, and why R0.10 does not stand in its way

**Status:** findings, not a spec. Nothing here is a rule until spec 001 carries
it (see "What has to happen first").

## The question

An agent implementing "fetch an external website" reported that it could not
use `crawl4ai` for a web connector, because a spec rule says only three things
may reach the network, MLflow among them. Should that rule be relaxed?

**No.** The rule allows a web connector already. What is actually in the way is
where the crawler runs and what it hands back.

## What R0.10 says

`specs/000-overview.md`, R0.10: "exactly three packages may reach the network,
and a model is asked only on a cache miss."

| Package | Reaches the network to |
|---|---|
| `dossier.infrastructure.connectors` | fetch source payloads |
| `dossier.infrastructure.models` | ask a model |
| `dossier.infrastructure.tracking` | send records to MLflow |

It names three **packages**, not three **libraries**. A web connector is a
connector: `crawl4ai` imported inside `src/dossier/infrastructure/connectors/`
(say `web.py`) and nowhere else is allowed by R0.10 as written. That is how
`atlassian`, `jira` and `requests` already live there
(`tests/architecture/imports_scan.py`). MLflow is the third package only
because tracking is not a connector.

## Why the rule should stay strict

R0.10 does not promise "no network". It promises that **everything right of the
hash boundary is reproducible**: a connector's output is frozen as an immutable
snapshot (R0.2), and everything after it can be replayed byte for byte (R4.7,
R0.4). A fourth package that reached the web, whether a converter,
`application/` or a stage, would end that promise. The boundary has already
been widened twice (R0.1 was superseded by R0.9, and R0.9 by R0.10), each time
with a written reason and without changing what it guarantees. "A library wants
the network" is not such a reason, because the library can go inside
`connectors/`.

## What is actually in the way

### 1. `crawl4ai` as a converter is forbidden, and should be

Spec 008 (`specs/008-conversion.md`): "A converter that downloaded would put
the network on the path every artifact is made on." If the crawler was placed in
conversion, the fix is to move it into `connectors/`, not to change the rule.

### 2. R1.2: `fetch` returns the payload byte for byte as received

`crawl4ai`'s headline output is cleaned Markdown, and that is a conversion. A
connector that returned it would break R1.2 and would freeze crawl4ai's
cleaning, from whatever version was installed that day, into the snapshot. The
split that fits the specs:

- **Connector (left of the boundary):** fetch the page and snapshot the raw HTML
  exactly as received. If a page needs JavaScript to render, the rendered DOM
  can be what is snapshotted, but the spec must say so and name the media type.
- **Converter (right of the boundary, spec 008):** HTML to Markdown, cached and
  replayable like every other conversion.

### 3. `crawl4ai` can call an LLM itself

Its LLM extraction and filtering strategies ask a model from inside the crawler.
That would be a model call outside `dossier.infrastructure.models`, with no cache
key, no provenance record (R0.3), and a call count `FakeModelClient` cannot see.
That is a real R0.10 violation. Those features have to stay off, and extraction
belongs in a pipeline stage.

### 4. A web connector is not specified yet

Spec 001 covers the folder, Jira and Confluence connectors. Under the working
agreement, unspecified behaviour is not implemented, so a web connector needs
rules in spec 001 before any code. It has to decide at least:

- **Keys** it declares (R1.10): seed URLs, crawl depth, same-domain restriction,
  include/exclude patterns, whether JavaScript is rendered.
- **Item key**: how a URL becomes a stable key (normalisation: scheme, trailing
  slash, query string, fragment).
- **`remote_version`**: `ETag` or `Last-Modified` when the server sends them,
  otherwise `None` (R1.5).
- **`lists_everything`** (R1.11): a crawl has no server-side "changed since", so
  it most likely lists everything, and sync computes tombstones against it.
- **Media type** of the payload (see R1.14 for how Jira names its own).
- **Attachments** (R1.6): whether linked PDFs and images are attachments of the
  page that links them.
- **Read-only** (R1.1): `GET` only.
- **Credentials** (R1.8): if a site needs auth, from the environment only.

## A gap in the check itself

Neither `crawl4ai` nor `playwright` is in `NETWORK_MODULES`
(`tests/architecture/imports_scan.py`). Today the R0.10 test would stay green if
either were imported from `domain/` or `application/`. Both should be added,
along the lines of R0.10's own "counting `mlflow` is what gives it teeth". That
change makes the rule stricter, not looser.

## Recommendation

1. Leave R0.10 as it is.
2. Amend spec 001 with a `web` connector (`/discover`): raw HTML snapshotted,
   GET only, `crawl4ai`'s LLM features off, the decisions above answered.
3. Put HTML to Markdown in spec 008 as a converter, right of the boundary.
4. Add `crawl4ai` and `playwright` to `NETWORK_MODULES`, and add a row to the
   R0.10 test showing `crawl4ai` imported outside `connectors/` is a violation.
5. Say in the commit adding the dependency why it was added: a browser and a
   Chromium download are a lot to add, and `httpx` plus a converter may be
   enough for static pages.
