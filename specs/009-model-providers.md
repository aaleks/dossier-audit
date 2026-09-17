# 009 — Model providers

**Status:** Implemented
**Rules:** R9.1 – R9.15

## Purpose

`dossier` asks models from more than one provider: hosted APIs -- Anthropic,
OpenAI and Google's Gemini -- and local models -- Ollama, and models such as Qwen
served by vLLM. Any of them may be reached directly or through OpenWebUI. None
of that may break R0.5. A stage key holds the model identifier and not the
endpoint (R5.3 row 4), so the identifier has to pin the weights. Without that,
re-pulling a model changes the answers under an unchanged key, and a cache hit
stops meaning that nothing relevant changed.

## Naming a model, and where it is served

`model:` says **what** answers. **Where** it is served is per-machine, is read
from the environment, and is part of no key -- so the same pipeline shares one
cache between a laptop and a GPU server.

| Provider | Pinned identifier | Reached at | API key | Checked before the first call |
|---|---|---|---|---|
| `anthropic` | `anthropic:claude-sonnet-4-5-20250929` (R0.6) | `DOSSIER_ANTHROPIC_URL`, default Anthropic's API | `DOSSIER_ANTHROPIC_API_KEY` | nothing |
| `openai` | `openai:gpt-4o-2024-08-06`, `openai:gpt-5.4-mini` (R9.14) | `DOSSIER_OPENAI_URL`, default `https://api.openai.com/v1` | `DOSSIER_OPENAI_API_KEY` | nothing |
| `gemini` | `gemini:gemini-3.5-flash-lite` (R9.10) | `DOSSIER_GEMINI_URL`, default `https://generativelanguage.googleapis.com/v1beta/openai` | `DOSSIER_GEMINI_API_KEY` | nothing |
| `ollama` | `ollama:qwen2.5:7b@sha256:7f3c29a1` | `DOSSIER_OLLAMA_URL`, default `http://localhost:11434` | `DOSSIER_OLLAMA_API_KEY` | the tag's digest (R9.4) |
| `hf`, served by vLLM | `hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b` | `DOSSIER_HF_URL`, no default | `DOSSIER_HF_API_KEY` | the served repo (R9.6); the revision is declared |

The provider is whatever precedes the first `:`. A provider is a package
declaring a `dossier.models` entry point, the same way connectors and converters
register (R1.7, R8.7); the five above ship in `dossier` through that group with
no special case. Each provider states its own pinned form here, as R0.6 leaves it
to do.

**OpenWebUI is a URL, not a provider.** It passes requests through to Ollama, to
vLLM, or to a hosted provider such as Gemini, and the identifier still names the
backend's pinned form. An OpenWebUI model name is an alias its administrator can
re-point, which is exactly what R0.6 refuses. Reaching a model through OpenWebUI
is a matter of pointing that provider's URL at it -- `DOSSIER_GEMINI_URL` at its
OpenAI-compatible route, `http://localhost:8080/api`, and `DOSSIER_OLLAMA_URL` at
its Ollama passthrough, `http://localhost:8080/ollama` -- and putting OpenWebUI's
API key in that provider's key variable. The provider's own name for the model is
sent as-is; for Gemini, as for Anthropic, nothing checks what it is routed to.

**The project's default is `gemini:gemini-3.5-flash-lite`, reached through a
local OpenWebUI.** A default is a value written into a pipeline's `model:` and
into `.env.example`, not a fallback in code: `model:` stays required, so a
committed pipeline always says which model answered it.

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
- **Status:** MET

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
- **Proved by:** `tests/acceptance/test_R009_2__endpoints_come_from_the_environment.py`
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

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
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | vLLM reports `Qwen/Qwen2.5-7B-Instruct` for `hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b` | the run proceeds |
| 2 | vLLM reports `Qwen/Qwen2.5-14B-Instruct` | the run stops naming both; 0 model calls |
| 3 | *counter-example* — the right repository loaded at a different revision | not detected; the revision is declared, not verified (R9.5) |

### R9.7 — a model reached through OpenWebUI is keyed by its backend's pinned identifier, never by an OpenWebUI model name

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.keys`)
- **Proved by:** `tests/unit/test_R009_7__openwebui_is_an_endpoint_not_a_provider.py`
- **Status:** MET

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
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `DOSSIER_OLLAMA_API_KEY` set and OpenWebUI answering 401 | the message names the URL and the status, not the key |
| 2 | a completed run | no manifest or provenance field holds the key |
| 3 | `api_key:` in `pipeline.yaml` | load-time error naming the key |
| 4 | *counter-example* — "`DOSSIER_OLLAMA_API_KEY` is not set" in an error | allowed; naming the variable is not disclosing its value |

### R9.9 — an OpenAI model is pinned only by a dated snapshot

`gpt-4o` is an alias OpenAI moves to each new snapshot. The snapshot ends in its
release date, written `-YYYY-MM-DD` -- not Anthropic's `-YYYYMMDD` (R0.6).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id`)
- **Proved by:** `tests/unit/test_R009_9__an_openai_model_is_pinned_by_a_dated_snapshot.py`
- **Status:** SUPERSEDED by R9.14

| # | Given | Then |
|---|-------|------|
| 1 | `openai:gpt-4o-2024-08-06` | accepted |
| 2 | `openai:gpt-4o` | refused, naming the identifier; an alias moves to each new snapshot |
| 3 | `openai:chatgpt-4o-latest` | refused |
| 4 | *counter-example* — `anthropic:claude-sonnet-4-5-20250929` | not this rule's form; R0.6 pins it |

### R9.10 — a Gemini model is pinned by a stable model code, never by a `latest`, preview or experimental name

Google names a model three ways: a stable code, which it documents as not
changing; a `-latest` name, which it re-points to each release; and preview and
experimental names, which it may replace under the same name. Only the first is a
pin. Gemini reports no digest, so this pin -- like Anthropic's -- rests on the
provider's documentation, and nothing is checked before the first call.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id`)
- **Proved by:** `tests/unit/test_R009_10__a_gemini_model_is_pinned_by_a_stable_code.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gemini:gemini-3.5-flash-lite` | accepted |
| 2 | `gemini:gemini-flash-lite-latest` | refused, naming the identifier; `-latest` is re-pointed at each release |
| 3 | `gemini:gemini-3-flash-preview` | refused; a preview can be replaced under the same name |
| 4 | *counter-example* — `openai:gpt-4o-2024-08-06` | not this rule's form; R9.14 pins it |

### R9.11 — a `.env` file in the working directory supplies only what the environment leaves unset

Endpoints and keys are per-machine (R9.2, R9.8), and a `.env` file saves
exporting them by hand. `dossier.config` reads it into what that package reads
the environment through; it never writes the process environment. `.env` is
git-ignored, and `.env.example` is its committed template.

- **Kind:** deterministic
- **Layer:** config (`dossier.config.environment`)
- **Proved by:** `tests/unit/test_R009_11__a_dotenv_file_fills_only_what_the_environment_leaves_unset.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `.env` holds `DOSSIER_GEMINI_URL=http://localhost:8080/api`, and the shell sets nothing | requests go to `http://localhost:8080/api` |
| 2 | the same `.env`, and the shell sets `DOSSIER_GEMINI_URL=https://generativelanguage.googleapis.com/v1beta/openai` | requests go to Google; the shell wins |
| 3 | no `.env` in the working directory | not an error; each provider's default applies (R9.2) |
| 4 | *counter-example* — `.env` sets `PATH=/opt/other/bin` | ignored; only `DOSSIER_` variables are read from it, and the process environment is unchanged |

### R9.12 — an OpenAI-compatible provider sends each completion to `<url>/chat/completions`, naming the model as its provider does

`openai`, `gemini` and `hf` all speak the OpenAI chat-completions API -- vLLM
serves it, and so does OpenWebUI's `/api` route -- so one client reaches all
three. Ollama is reached through its native API, which is what OpenWebUI's
`/ollama` passthrough speaks, and Anthropic through its own; each is a later
rule. The model is named as its provider names it: the identifier without its
provider prefix, and for `hf` also without the `@revision` dossier pins it by
(R9.5), because vLLM serves a model under its repository name.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.models.openai_compatible`)
- **Proved by:** `tests/unit/test_R009_12__openai_compatible_requests.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gemini:gemini-3.5-flash-lite` reached at `http://localhost:8080/api` | one POST to `http://localhost:8080/api/chat/completions`, with model `gemini-3.5-flash-lite`, temperature 0, and the stage's JSON Schema as `response_format` |
| 2 | `DOSSIER_GEMINI_API_KEY` set | sent as `Authorization: Bearer`; unset, no `Authorization` header at all |
| 3 | the server answers 200 | `choices[0].message.content` is returned verbatim; validating it stays the stage's job (R6.1) |
| 4 | the server answers 401, or any other non-2xx status | an error naming the URL and the status, never the key (R9.8 row 1) |
| 5 | *counter-example* — `anthropic:claude-sonnet-4-5-20250929` | not this rule's; Anthropic has its own API (R9.15) |

### R9.13 — an Ollama provider sends each completion to `<url>/api/chat`, naming the model by its tag

Ollama is reached through its native API, which is also what OpenWebUI's
`/ollama` passthrough speaks, so the same client reaches Ollama directly and
through OpenWebUI (R9.7). The model is named by its tag: the identifier without
its provider prefix and without the `@sha256:` digest dossier pins it by (R9.3),
which Ollama does not accept as part of a name. The digest is checked separately,
before the first completion (R9.4).

Thinking is turned off. Ollama exposes `think`, and a reasoning model left to it
spends its budget on a chain of thought before answering -- which, under a
constrained `format`, it can exhaust entirely, returning an empty string. Asking
`qwen3.5:9b` to judge one calibration case took 268 seconds and produced nothing;
the same case with `think` false took 19 seconds and produced a verdict. Every
completion dossier asks for is structured (R6.1), so this is a property of the
request and not of the model: it is sent on every call, not configured per tag.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.models.ollama`)
- **Proved by:** `tests/unit/test_R009_13__ollama_requests.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `ollama:qwen2.5:7b@sha256:7f3c29a1` reached at `http://localhost:8080/ollama` | one POST to `http://localhost:8080/ollama/api/chat`, with model `qwen2.5:7b`, `stream` false, `think` false, temperature 0 in `options`, and the stage's JSON Schema as `format` |
| 2 | `DOSSIER_OLLAMA_API_KEY` set | sent as `Authorization: Bearer`; unset, no `Authorization` header at all |
| 3 | the server answers 200 | `message.content` is returned verbatim; validating it stays the stage's job (R6.1) |
| 4 | the server answers 401, or any other non-2xx status | an error naming the URL and the status, never the key (R9.8 row 1) |
| 5 | *counter-example* — `gemini:gemini-3.5-flash-lite` | not this rule's; R9.12 reaches it |

### R9.14 — an OpenAI model is pinned by a dated snapshot or a stable code, never by a name OpenAI moves

R9.9 read the dated snapshot as the only pin OpenAI offers, and for the `gpt-4o`
generation it was: every identifier was either a snapshot or an alias pointing at
one. Later families are published under a stable code with no snapshot behind it
-- `gpt-5.4-mini` -- which R9.9 refuses, and a correctly pinned model refused is
the same failure as a floating one accepted, pointing the other way.

So OpenAI is pinned the way Gemini is (R9.10): what the provider documents as
moving is refused, and what it does not is a pin resting on that documentation.
Two kinds of OpenAI name move. The `-latest` and preview markers say so in the
name. The bare family aliases do not -- nothing in the shape of `gpt-4o`
distinguishes it from `gpt-5.4-mini` -- so those are refused by name, from a
short list where each entry is a claim about a provider someone confirmed, the
way R0.6's fixed ids are.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id`)
- **Proved by:** `tests/unit/test_R009_14__an_openai_model_is_pinned_by_a_snapshot_or_a_stable_code.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `openai:gpt-5.4-mini` | accepted; a stable code with no snapshot behind it |
| 2 | `openai:gpt-4o-2024-08-06` | accepted; a dated snapshot is still a pin |
| 3 | `openai:gpt-4o` | refused, naming the identifier; OpenAI moves it to each new snapshot |
| 4 | `openai:chatgpt-4o-latest` | refused; `-latest` is re-pointed at each release |
| 5 | *counter-example* — `anthropic:claude-sonnet-4-5-20250929` | not this rule's form; R0.6 pins it |

### R9.15 — an Anthropic provider sends each completion to `<url>/messages`, naming the model as Anthropic does

Anthropic is reached through its own Messages API, which R9.12 and R9.13 each
left to a later rule. The model is named as Anthropic names it: the identifier
without its provider prefix, which for Anthropic is already the dated snapshot
R0.6 pins by. The key travels in Anthropic's own header, `x-api-key`, never as
`Authorization: Bearer`; the API version is named on every request, because
Anthropic changes behaviour by that header and not by the URL.

Nothing about sampling is sent. R9.12 and R9.13 ask for temperature 0 so the
same prompt asks for the same answer; Anthropic's current generation refuses
sampling parameters outright, and dossier's reproducibility was never the
model's to provide -- a model is reached only on a cache miss, and every answer
it gives is cached under a key that names the prompt, the schema and the pinned
model (R0.10, spec 005). `max_tokens` is required by the API and is a fixed
ceiling, 16000, sized for a request that is not streamed.

A reply is a list of content blocks, and the answer is the first of type `text`:
a model that thinks by default puts its thinking first, and that is not the
answer. A reply that stops with `refusal` has no text block at all, and is
reported as what it is rather than handed to the stage as an empty answer for
R6.2 to retry.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.models.anthropic`)
- **Proved by:** `tests/unit/test_R009_15__anthropic_requests.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `anthropic:claude-sonnet-4-5-20250929` reached at `https://api.anthropic.com/v1` | one POST to `https://api.anthropic.com/v1/messages` with header `anthropic-version: 2023-06-01`; body: model `claude-sonnet-4-5-20250929`, one `user` message holding the prompt, `max_tokens` 16000, the stage's JSON Schema as `output_config.format` of type `json_schema`, and no `temperature`, `top_p` or `top_k` |
| 2 | `DOSSIER_ANTHROPIC_API_KEY` set | sent as `x-api-key`, with no `Authorization` header; unset, no `x-api-key` header at all |
| 3 | the server answers 200 with a `thinking` block and then a `text` block | the `text` block's text is returned verbatim; validating it stays the stage's job (R6.1) |
| 4 | the server answers 200 with `stop_reason` `refusal` and no `text` block | an error naming the model and the stop reason; never an empty string handed to the stage as an answer |
| 5 | the server answers 401, or any other non-2xx status | an error naming the URL and the status, never the key (R9.8 row 1) |
| 6 | *counter-example* — `gemini:gemini-3.5-flash-lite` | not this rule's; R9.12 reaches it |
