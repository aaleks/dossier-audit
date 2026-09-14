# 009 — Model providers

**Status:** Partially implemented
**Rules:** R9.1 – R9.8

## Purpose

`dossier` asks models from more than one provider: Anthropic's API, and local
models -- Ollama, and models such as Qwen served by vLLM, reached directly or
through OpenWebUI. None of that may break R0.5. A stage key holds the model
identifier and not the endpoint (R5.3 row 4), so the identifier has to pin the
weights. Without that, re-pulling a model changes the answers under an unchanged
key, and a cache hit stops meaning that nothing relevant changed.

## Naming a model, and where it is served

`model:` says **what** answers. **Where** it is served is per-machine, is read
from the environment, and is part of no key -- so the same pipeline shares one
cache between a laptop and a GPU server.

| Provider | Pinned identifier | Reached at | Checked before the first call |
|---|---|---|---|
| `anthropic` | `anthropic:claude-sonnet-4-5-20250929` (R0.6) | `DOSSIER_ANTHROPIC_URL`, default Anthropic's API | nothing |
| `ollama` | `ollama:qwen2.5:7b@sha256:7f3c29a1` | `DOSSIER_OLLAMA_URL`, default `http://localhost:11434` | the tag's digest (R9.4) |
| `hf`, served by vLLM | `hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b` | `DOSSIER_HF_URL`, no default | the served repo (R9.6); the revision is declared |

The provider is whatever precedes the first `:`. A provider is a package
declaring a `dossier.models` entry point, the same way connectors and converters
register (R1.7, R8.7); the three above ship in `dossier` through that group with
no special case. Each provider states its own pinned form here, as R0.6 leaves it
to do.

**OpenWebUI is a URL, not a provider.** It passes requests through to Ollama or
to vLLM, and the identifier still names the backend's pinned form. An OpenWebUI
model name is an alias its administrator can re-point, which is exactly what
R0.6 refuses.

**A vLLM revision is declared, not verified.** vLLM reports which repository it
loaded and not which revision, so `dossier` checks the first and records the
second as stated. Whoever starts vLLM with `--revision` is responsible for it
matching.

## Must hold

### R9.1 — a model whose provider no installed package provides is refused at load time

The provider is what precedes the first `:`, so an Ollama tag keeps its own
colon. A provider nothing provides is found before any work begins, not at the
first cache miss an hour into a run.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.load`)
- **Proved by:** `tests/unit/test_R009_1__an_unknown_provider_is_refused_at_load_time.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `model: anthropic:claude-sonnet-4-5-20250929` | resolves to the `anthropic` provider |
| 2 | `model: ollama:qwen2.5:7b@sha256:7f3c29a1` | resolves to `ollama`; the tag's colon is not a provider boundary |
| 3 | a package declaring `dossier.models` entry point `lmstudio` | `lmstudio:...` resolves, with no edit to `dossier` |
| 4 | `model: mistral:mistral-large-2411` with no package providing it | load-time error naming the providers available |
| 5 | *counter-example* — `--replay` of a run pinned to `ollama:...`, on a machine with no Ollama provider | not refused; a replay asks no model (R4.7, R0.9) |

### R9.2 — where a provider is reached is read from the environment, never from committed configuration

- **Kind:** deterministic
- **Layer:** config (`dossier.config.endpoints`)
- **Proved by:** `tests/unit/test_R009_2__endpoints_come_from_the_environment.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_OLLAMA_URL=http://gpu-01:11434` | requests go to `http://gpu-01:11434` |
| 2 | the same identifier reached at `http://localhost:11434` and at `http://gpu-01:11434` | the same keys, and one shared cache (R5.3 row 4) |
| 3 | `DOSSIER_HF_URL` unset at the first cache miss | the run stops before any model call, naming the variable |
| 4 | `url:` in `pipeline.yaml` | load-time error naming the key; an endpoint is not committed |
| 5 | *counter-example* — `DOSSIER_HF_URL` unset and every stage served from cache | completes; no model is reached, so no endpoint is needed (R0.9) |

### R9.3 — an Ollama model is pinned only by its digest

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id`)
- **Proved by:** `tests/unit/test_R009_3__an_ollama_model_is_pinned_by_digest.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `ollama:qwen2.5:7b@sha256:7f3c29a1` | accepted |
| 2 | `ollama:qwen2.5:7b` | refused, naming the identifier; a tag moves when the model is re-pulled |
| 3 | `ollama:qwen2.5:latest@sha256:7f3c29a1` | accepted; the digest pins it, and the tag only names what to ask for |
| 4 | *counter-example* — `anthropic:claude-sonnet-4-5-20250929` | not this rule's form; R0.6 pins it |

### R9.4 — a run stops before its first model call if the server's digest for the tag is not the pinned one

Checked on the first cache miss, because that is the first moment a model is
reached at all (R0.9).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id.check_served`)
- **Proved by:** `tests/unit/test_R009_4__a_re_pulled_ollama_model_stops_the_run.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | the server reports `7f3c29a1` for `qwen2.5:7b` | the run proceeds; one digest request for the run |
| 2 | the model was re-pulled and the server now reports `e04b6d52` | the run stops naming both digests; 0 model calls and nothing cached |
| 3 | `DOSSIER_OLLAMA_URL` pointing at OpenWebUI's Ollama passthrough, `https://ai.example.internal/ollama` | checked the same way (R9.7) |
| 4 | *counter-example* — every stage served from cache | no digest request and no model call (R0.9) |

### R9.5 — a model served by vLLM is pinned by its Hugging Face repository and revision

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id`)
- **Proved by:** `tests/unit/test_R009_5__a_vllm_model_is_pinned_by_repo_and_revision.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b` | accepted |
| 2 | `hf:Qwen/Qwen2.5-7B-Instruct` | refused; it names no revision |
| 3 | `hf:Qwen/Qwen2.5-7B-Instruct@main` | refused; a branch moves |
| 4 | *counter-example* — `ollama:qwen2.5:7b@sha256:7f3c29a1` | not this rule's form; R9.3 pins it |

### R9.6 — a run stops before its first model call if the served model names a different repository

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id.check_served`)
- **Proved by:** `tests/unit/test_R009_6__a_vllm_serving_another_repo_stops_the_run.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | vLLM reports `Qwen/Qwen2.5-7B-Instruct` for `hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b` | the run proceeds |
| 2 | vLLM reports `Qwen/Qwen2.5-14B-Instruct` | the run stops naming both; 0 model calls |
| 3 | *counter-example* — the right repository loaded at a different revision | not detected; the revision is declared, not verified (R9.5) |

### R9.7 — a model reached through OpenWebUI is keyed by its backend's pinned identifier, never by an OpenWebUI model name

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R009_7__openwebui_is_an_endpoint_not_a_provider.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `ollama:qwen2.5:7b@sha256:7f3c29a1` reached through `https://ai.example.internal/ollama` | the same keys as reaching Ollama directly |
| 2 | `model: openwebui:my-qwen` | refused; an OpenWebUI name is an alias its administrator can re-point |
| 3 | *counter-example* — `DOSSIER_HF_URL` set to OpenWebUI's OpenAI-compatible route | allowed; OpenWebUI is where, not what |

### R9.8 — a model endpoint's API key comes from the environment and never reaches configuration, logs, ledger, manifest or provenance

R1.8's promise, for model endpoints.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.credentials`)
- **Proved by:** `tests/unit/test_R009_8__model_api_keys_are_never_disclosed.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_OLLAMA_API_KEY` set and OpenWebUI answering 401 | the message names the URL and the status, not the key |
| 2 | a completed run | no manifest or provenance field holds the key |
| 3 | `api_key:` in `pipeline.yaml` | load-time error naming the key |
| 4 | *counter-example* — "`DOSSIER_OLLAMA_API_KEY` is not set" in an error | allowed; naming the variable is not disclosing its value |
