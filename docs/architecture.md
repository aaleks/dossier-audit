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

In the code the boundary is three packages: **`dossier.infrastructure.connectors`
fetches source payloads, `dossier.infrastructure.models` asks a model, and
`dossier.infrastructure.tracking` sends records to MLflow.** Nothing else may
import a network client -- `mlflow` included -- and everything right of the line
is a pure function of content hashes.

This is R0.10, which supersedes R0.9 (two packages) and R0.1 (connectors only).
It is checked by `tests/architecture/test_R000_10__three_packages_reach_the_network.py`,
which walks every module with `ast` — so a lazy import inside a function body is
caught as readily as one at module scope.

The line is not "no network right of it". A stage asks a model, and asking is the
point; R0.1 said otherwise and was true only while no model client existed. What
makes a run from six months ago reproducible is that the answer was keyed, cached
with its provenance record, and never asked again -- a judge's verdict included
(R7.18). Tracking only *sends*: its port returns nothing read from the server, so
nothing MLflow holds can enter a key, a manifest or a score (R10.4).

## Boundary 2 — the purity boundary

**`dossier.domain` imports nothing but the standard library and pydantic.**

No file IO, no network, no clock, no `os.environ`, no YAML, no CLI framework, no
tracking SDK. A function in `domain/` takes what it needs as an argument, which
is why its tests need no fixtures and run in milliseconds — and why mutation
testing is affordable there and nowhere else.

## The layers

| Package | Holds | Rule |
|---|---|---|
| `dossier.domain` | Decisions: key composition, reference resolution, the normalisation projection, span checking, scoring, model-id validation. Protocols and value objects in `domain/ports.py`. | Imports stdlib and pydantic only. Deterministic: no clock, no randomness, no IO. |
| `dossier.application` | Use cases: `sync`, `convert`, `run`, `plan`, `eval`. Orchestrates domain decisions over ports. | Takes the connector, the store and the model client as arguments. Never constructs one. |
| `dossier.infrastructure` | Connectors, converters, the snapshot store, the ledger, model clients, MLflow tracking. | Wiring, not judgement. A heavy SDK (`mlflow`) is imported inside the function that uses it; `httpx` is imported at module scope by the packages left of the boundary, which is where it belongs. |
| `dossier.config` | Loading and validating `sources.yaml` and `pipeline.yaml`; reading credentials. | The only package that reads `os.environ`. |
| `dossier.cli` | The typer app: flags, output, exit codes. | The only package that calls `sys.exit`. |

Dependencies point one way:

```
cli ──▶ config ──▶ application ──▶ domain
                          │            ▲
                          └──▶ infrastructure ──┘   (via domain.ports only)
```

`infrastructure` implements protocols declared in `domain.ports`. It is never
imported by `domain` and never by `application` — the composition happens in
`cli`, which is the only place that knows which concrete implementation is in
play. That is what lets every use case run against a fake.

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
   calls. Counting calls is not a nicety here: R2.5, R4.6, R5.5 and R5.7 are all
   claims about how many calls happened.
