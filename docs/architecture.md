# Architecture — two boundaries

`specs/` describes what `dossier` does. This file describes how the code is
arranged so that those rules stay provable. It is not a spec: nothing here is a
product claim, and nothing here carries a rule id. It is enforced by
`tests/architecture/`.

There are exactly two boundaries. Everything else is ordinary structure.

## Boundary 1 — the hash boundary

```
   sync  ──▶  store  ┃  convert  ──▶  stages  ──▶  score
                     ┃
  mutable, remote,   ┃   local, frozen, identical on every run
  not repeatable     ┃
```

In the code the boundary is four packages: **`dossier.infrastructure.connectors`
fetches source payloads, `dossier.infrastructure.models` asks a model, for an
answer or a vector, `dossier.infrastructure.tracking` sends records to MLflow,
and `dossier.infrastructure.index` writes the embedding index.** Nothing else
may import a network client -- `mlflow` and `psycopg` included -- and everything
right of the line is a pure function of content hashes. The index is derived
data: the port that writes it reads back only the ids and hashes of what it
holds (spec 018), and the port a search reads it through hands what it reads
to the terminal and MLflow, never to a key, a manifest or a score (spec 019).

This is R0.17, which supersedes R0.16 (the index before search), R0.10 (three
packages), R0.9 (two) and R0.1 (connectors only). It is checked by
`tests/architecture/test_R000_17__four_packages_reach_the_network.py`,
which walks every module with `ast` — so a lazy import inside a function body is
caught as readily as one at module scope.

The line is not "no network right of it". A stage asks a model, and asking is the
point; R0.1 said otherwise and was true only while no model client existed. What
makes a run from six months ago reproducible is that the answer was keyed, cached
with its provenance record, and never asked again -- a judge's verdict included
(R7.18). Tracking sends records. What it hands back to the rest of `dossier` is
only what specs 012 to 015 fence, each through a port of its own: what a
registry says about a dataset, a pipeline version or a prompt version it
published or found, and reviewers' verdicts, for `dossier review pull` alone
(R15.5). The `Tracker` port itself returns nothing read from the server, so
nothing MLflow holds can enter a key, a manifest or a score through it (R10.4).

## Boundary 2 — the purity boundary

**`dossier.domain` imports nothing but the standard library and pydantic.**

No file IO, no network, no clock, no `os.environ`, no YAML, no CLI framework, no
tracking SDK. A function in `domain/` takes what it needs as an argument, which
is why its tests need no fixtures and run in milliseconds — and why mutation
testing is affordable there and nowhere else.

Not `io` either, and that one has a visible consequence. `page_images` is packed
by a format defined in `domain/conversion.py` rather than by `zipfile`, for two
reasons: a module that can open a stream can open a file, and a stored ZIP
carries an external-attributes field and a version-made-by byte that are set
from the platform — while a container of pages has to be byte-identical wherever
it is built (R8.11, R5.6). The format lives in `domain` because `application`
unpacks it and may import nothing else. What it costs is unzipping an artifact
with a standard tool.

## The layers

| Package | Holds | Rule |
|---|---|---|
| `dossier.domain` | Decisions: key composition, reference resolution, the normalisation projection, span checking and its three grounding states, scoring, model-id validation, and the container format a multi-page conversion is packed into. Protocols and value objects in `domain/ports.py`. | Imports stdlib and pydantic only. Deterministic: no clock, no randomness, no IO. |
| `dossier.application` | Use cases: `sync`, `convert`, `run`, `plan`, `eval`, `datasets`, `prompts`, `review`, `gc`, `status`, `embed`, `search`. Orchestrates domain decisions over ports. | Takes the connector, the store and the model client as arguments. Never constructs one. |
| `dossier.infrastructure` | Connectors, converters, chunkers, the snapshot store, the cache, the ledger, model clients, MLflow tracking, the embedding index. | Wiring, not judgement. A heavy SDK (`mlflow`, `playwright`) is imported inside the function that uses it, and the connectors import `httpx` the same way. The model clients and tracking import `httpx` at module scope, and the index imports `psycopg` at module scope. |
| `dossier.config` | Loading and validating `sources.yaml`, `pipeline.yaml` and an index's declaration; reading credentials. | The only package that reads `os.environ`. |
| `dossier.cli` | The typer app: flags, output, exit codes. One module per command (`sync`, `run`, `convert`, `calibrate`, `eval`, `gc`, `status`, `embed`, `search`, `dataset`, `review`, `prompts`); `main` registers them and is the entry point; `bootstrap` builds the model client, the tracker and the registries they are handed. | The only package that calls `sys.exit`. |

Dependencies point one way:

```
        ┌──▶ config ──────────┐
cli ────┼──▶ application ─────┼──▶ domain
        └──▶ infrastructure ──┘   (infrastructure via domain.ports only)
```

`cli` may import every layer; `config`, `application` and `infrastructure` may
import `domain` and nothing else (`tests/architecture/test_layer_contracts.py`).
`infrastructure` implements protocols declared in `domain.ports`. It is never
imported by `domain` and never by `application` — the composition happens in
`cli`, which is the only place that knows which concrete implementation is in
play. That is what lets every use case run against a fake: a test replaces a
builder in `dossier.cli.bootstrap`, and every command reaches its builders
through that module, so the replacement is what it calls. The one builder not
there is `build_review_source`, which lives in `dossier.cli.review` with the one
command allowed to call it (R15.5).

## Where a decision belongs

The most common decay in a project like this is not a bad import. It is a
**decision that landed in the wrong layer**: an `if` on a threshold, a precedence
choice, a validity check, sitting in `infrastructure/` next to the call it
guards, where no test can reach it without a server.

The test: *could this be asserted with a plain dict and no fixtures?* If yes, it
belongs in `domain/`, whatever else surrounds it.

| Looks like | Actually is | Goes in |
|---|---|---|
| "skip the fetch if the version matches" | a decision | `domain` |
| "issue the HTTP GET" | wiring | `infrastructure` |
| "reject a floating model alias" | a decision | `domain` |
| "read `JIRA_TOKEN` from the environment" | configuration | `config` |
| "print the plan table and exit 1" | presentation | `cli` |

## Deliberate divergences from the toolchain this repo inherited

The `.claude/` toolchain came from a LangChain project. Two things were changed
rather than carried over, and both are worth stating once:

1. **No import-linter.** The layer contracts are checked by an `ast` walk in
   `tests/architecture/test_layer_contracts.py` instead. It is one fewer
   dependency, it runs on Windows without a shell out, and it can express the
   hash boundary — "no network import anywhere in this subtree, including inside
   a function" — which an import-linter contract cannot.
2. **No `langchain`, and therefore no `FakeListChatModel`.** `dossier` calls
   models through its own `ModelClient` protocol in `domain/ports.py`, and the
   test suite uses `FakeModelClient`, which returns canned responses and counts
   calls. Counting calls is not a nicety here: R2.15, R4.6, R5.5 and R5.10 are
   all claims about how many calls happened.
