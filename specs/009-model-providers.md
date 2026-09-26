# 009 — Model providers

**Status:** Partially implemented
**Rules:** R9.1 – R9.20

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
reached at all (R0.10).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.model_id.check_served`)
- **Proved by:** `tests/unit/test_R009_4__a_re_pulled_ollama_model_stops_the_run.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | the server reports `7f3c29a1` for `qwen2.5:7b` | the run proceeds; one digest request for the run |
| 2 | the model was re-pulled and the server now reports `e04b6d52` | the run stops naming both digests; 0 model calls and nothing cached |
| 3 | `DOSSIER_OLLAMA_URL` pointing at OpenWebUI's Ollama passthrough, `https://ai.example.internal/ollama` | checked the same way (R9.7) |
| 4 | *counter-example* — every stage served from cache | no digest request and no model call (R0.10) |

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

### R9.16 — a stage may hand a model image parts, and each provider sends them in its own native form

`ModelClient.complete` took a `str` and nothing else, so there was no way for
bytes to reach a model at all. That was the right shape while every artifact a
stage could name was text (R8.4 counter-example 4), and it stopped being right
the moment a step could name `page_images` (R3.11).

A part is bytes and a media type. What each provider does with it is the
provider's business and differs between all three, which is exactly why the
conversion happens at the edge rather than in `application`: a stage hands over
parts and never learns whether they became a data URI, a base64 source block or
an array beside the message.

A call with no parts sends what it sent before this rule. Not an empty array, not
a single-element content list -- the same bytes, so that no existing cache key
moves and no provider sees a request shape it did not see yesterday.

- **Kind:** deterministic
- **Layer:** infrastructure (`dossier.infrastructure.models`)
- **Proved by:** `tests/unit/test_R009_16__a_provider_sends_image_parts_in_its_own_form.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | an OpenAI-compatible provider, one `image/png` part | the message content is a list: the prompt as a `text` item, then an `image_url` item whose url is a `data:image/png;base64,` URI (R9.12) |
| 2 | `anthropic:claude-sonnet-4-5-20250929`, the same part | one `image` content block with `source.type` `base64`, `source.media_type` `image/png`, then the prompt as a `text` block (R9.15) |
| 3 | `ollama:qwen2.5:7b@sha256:7f3c29a1`, the same part | the message keeps its string `content` and gains an `images` array holding the part, base64, as Ollama's own API takes it (R9.13) |
| 4 | three parts in page order | three items, in that order, for every provider; a page order the caller chose is not a set |
| 5 | *counter-example* — a call with no parts | byte-identical to the request the same call made before this rule: no empty `images` key and no content list, so no cache key moves and no provider meets a shape it did not see yesterday |

### R9.17 — a model request answered 408, 409, 429 or 5xx, or not answered at all, is sent again up to twice before it fails

A rate limit is not an answer about the document. Before this rule, a single
`429` or `503` from a hosted provider, or from an OpenWebUI in front of one,
raised straight out of the client (R9.12 row 4) and stopped the run at the
document it happened on. A run over four hundred documents met one sooner or
later, on the endpoint the project uses by default.

The request is sent again **unchanged**. That makes it a different thing from
R6.2's retry, which re-asks with the validation error appended and so is a second
call, counted as one. This one happens inside a single `complete`: the stage sees
one answer, the fake counts one call (R5.5), and MLflow shows one LLM span
(R11.2). Nothing about it enters a key or a provenance record. The same bytes
were asked for, and the answer that came back is the answer.

The policy is the one both official SDKs apply, value for value, rather than one
invented here: at most **two** retries; a `Retry-After` (or `retry-after-ms`)
the server sends is waited for when it is above 0 and at most 60 s; otherwise the
wait is 0.5 s, then 1 s, doubling to at most 8 s, and each is shortened by up to
a quarter at random so that callers refused together do not come back together.
The retried statuses are the SDKs' too: `408`, `409`, `429` and every `5xx`,
Anthropic's `529` "overloaded" among them, and a request no server answered at
all -- refused, reset or timed out.

Everything else still fails on the first answer. A `401` is a key the server
refused, and sending it again would only send it twice. A `400` is a request it
could not read, and it will not read it differently a second time.

Which answers are retried and how long to wait are decisions, and they sit in
`domain/` with the jitter and the clock handed in. Sending the request again is
wiring, and sits in the one place every model client already sends through.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.retries`), infrastructure (`dossier.infrastructure.models._http`)
- **Proved by:** `tests/acceptance/test_R009_17__a_rate_limited_model_request_is_sent_again.py`, `tests/unit/test_R009_17__which_model_requests_are_retried_and_when.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gemini:gemini-3.5-flash-lite` at `http://localhost:8080/api` answers `429`, then `200` | two identical POSTs to `/chat/completions`; the `200`'s `choices[0].message.content` is returned, and the stage counts one call (R5.5) |
| 2 | the `429` carries `Retry-After: 3` | the second POST is sent 3 s after the first answer: the server's wait, not the backoff |
| 3 | `503` with no `Retry-After`, three times | three POSTs, waiting 0.5 s and then 1 s, each shortened by up to a quarter; then the error R9.12 row 4 describes -- the URL and `503`, never the key -- saying 3 attempts were made |
| 4 | the connection refused, then `200` | the answer, from the second attempt; a request no server answered is retried like a `503` |
| 5 | `anthropic:claude-sonnet-4-5-20250929` answers `529`, then `200` | the answer; the policy is every provider's, not one client's |
| 6 | a `429` carrying `Retry-After: 120` | the backoff's 0.5 s rather than two minutes, as both SDKs do; an answer asking for longer than 60 s is not waited for |
| 7 | *counter-example* — `401` | one POST, and the error at once; a key refused once is refused again |
| 8 | *counter-example* — `400` | one POST, and the error at once; a request the server could not read is not re-read |
| 9 | *counter-example* — a `200` whose content fails the stage's schema | not this rule's: the stage re-asks once with the error (R6.2), and that is a second call |

### R9.18 — a reply carries the tokens its provider counted, and a count the provider did not give is absent, never zero

Nothing `dossier` recorded said what a run cost. Every provider already says,
in its own words, on every answer -- and every client threw it away with the
rest of the body. The first question asked of a tool whose promise is "a new
audit in an afternoon" is what the afternoon cost, and it had no answer.

A reply is still text. `Reply` is a `str` carrying `input_tokens` and
`output_tokens`, so every caller that reads an answer as text reads this one
unchanged, and a client that reports nothing -- a test's fake among them -- is
still a `ModelClient`. Where each provider says it:

| Provider | Input | Output |
|---|---|---|
| OpenAI-compatible (`openai`, `gemini`, `hf`) | `usage.prompt_tokens` | `usage.completion_tokens` |
| `anthropic` | `usage.input_tokens` | `usage.output_tokens` |
| `ollama` | `prompt_eval_count` | `eval_count` |

A count the provider did not give is `None`. Not `0`: an OpenWebUI that strips
`usage` from what it passes through has not reported a free completion, and a
record saying it cost nothing would be a lie in a smaller font -- the reason
`source.page` is `null` rather than `1` for a document with no pages (R6.14).

Tokens are what an answer cost, not what it was asked, so they enter no key
(R0.5).

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.ports.Reply`, `dossier.domain.usage`), infrastructure (`dossier.infrastructure.models`)
- **Proved by:** `tests/unit/test_R009_18__a_reply_carries_the_tokens_its_provider_counted.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `gemini:gemini-3.5-flash-lite` at `http://localhost:8080/api` answers with `usage: {prompt_tokens: 1204, completion_tokens: 212}` | the reply is `choices[0].message.content`, as before, with `input_tokens` 1204 and `output_tokens` 212 |
| 2 | `anthropic:claude-sonnet-4-5-20250929` answers with `usage: {input_tokens: 1204, output_tokens: 212}` | the same counts, read from Anthropic's names |
| 3 | `ollama:qwen2.5:7b@sha256:7f3c29a1` answers with `prompt_eval_count: 1204, eval_count: 212` | the same counts, read from Ollama's |
| 4 | *counter-example* — the answer has no `usage` at all | both `None`; a count nobody gave is not `0` |
| 5 | *counter-example* — `usage.prompt_tokens` is `"many"`, `-3` or `true` | that count is `None`; what is not a count of tokens is not recorded as one |
| 6 | *counter-example* — a client that returns plain `str` | read as reporting nothing: both `None`, and it is still a `ModelClient` |

### R9.19 — `dossier run` asks a model about at most `N` of a step's documents at once, and nothing it writes depends on `N`

A run asked about one document at a time, so a step over four hundred documents
was four hundred round trips end to end, against a hosted provider that would
have answered ten at once. R9.17 is what makes asking several at once safe to
offer: the `429` it provokes is waited out rather than fatal.

`N` is per machine, like where a model is served. A hosted key with a high rate
limit and a laptop serving a local model want different values, and the same
pipeline runs on both. So it is `--concurrency N` on `dossier run`, else
`DOSSIER_CONCURRENCY` from the environment `.env` fills (R9.11), else **1**. It
is never read from `pipeline.yaml`: `pipeline_hash` is the hash of that file,
and a setting about speed would move it. It is 1 by default because a local
model often answers one request at a time. Four sent to it wait in its queue,
can outlast the client's timeout, and are then sent again by R9.17, which is
slower than sending one at a time.

No ceiling is imposed. `dossier` does not know a provider's limit, and a number
made up here would be a threshold nobody agreed.

`N` counts documents within one step. Steps still run in order, because a step
reads what the one before it produced (R3.3). The parts of one `per_part`
document are still asked one after another: a (step, document) is the unit of a
key and of a trace (R11.1), and it is what is handed to a worker whole.

Nothing about `N` reaches a key, the manifest, a provenance record or an
artifact. Results are collected in document order, whatever order they were
answered in, so the step lines and `runs/<run_id>/` are what the same run at
`N = 1` writes.

A run stops as it did: a request that still fails after R9.17's retries stops it
(R9.12 row 4). With several in flight, a document not yet started when one fails
is not started. The ones already asked are waited for, and cached if they were
answered, because an answer already paid for is not thrown away. The error the
run stops with is the first failing document's, in document order, which is the
one a run at `N = 1` stops with.

- **Kind:** deterministic
- **Layer:** domain (`dossier.domain.concurrency`), application (`dossier.application.run`), cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R009_19__a_run_asks_about_several_documents_at_once.py`, `tests/unit/test_R009_19__how_many_documents_are_asked_at_once.py`
- **Status:** MET

| # | Given | Then |
|---|-------|------|
| 1 | `INC-4821`, `INC-4822`, `INC-4901`, nothing cached, `dossier run incident-audit --concurrency 3`, and a model that answers none until all three are asked | all three asked before any is answered, and `extract: 3 document(s) · 0 from cache · 0 failed · 3,612 tokens in · 636 out`, the line R5.12 row 1 prints one at a time |
| 2 | the same three, answered in the order `INC-4901`, `INC-4822`, `INC-4821` | `runs/<run_id>/extract/` holds the same three files, byte for byte, as the same run with no flag; their provenance records differ in `run_id` alone |
| 3 | `DOSSIER_CONCURRENCY=2` in `.env`, no flag | never more than two asked at once |
| 4 | `DOSSIER_CONCURRENCY=2` and `--concurrency 3` | three: what is said on the command line wins over what the machine is set to |
| 5 | neither set | one at a time: the run this rule found |
| 6 | every request refused, `--concurrency 2` | `INC-4821` and `INC-4822` asked, `INC-4901` never; the run stops with the error R9.12 row 4 describes, as it does one at a time |
| 7 | *counter-example* — `--concurrency 0`, `-1` or `four`, or `DOSSIER_CONCURRENCY=2.5` | refused before any work, naming where the value came from -- `DOSSIER_CONCURRENCY is '2.5'; it takes a whole number of at least 1.` -- with exit 2 and nothing asked |
| 8 | *counter-example* — `concurrency: 3` in `pipeline.yaml` | refused at load time as a key the format does not have (R3.1): how fast a pipeline is run is not part of what it is |
| 9 | *counter-example* — one `per_part` document of four pages, `--concurrency 4` | its four pages asked one after another: `N` counts (step, document) pairs, not parts |

### R9.20 — a model that cannot be reached, or refuses, stops any command asking it in one line naming the pipeline, never a traceback

`dossier run` says it in one line and exits 2:
`incident-audit: POST http://localhost:8080/api/chat/completions failed: ... (after 3 attempts)`.
`calibrate` and `eval` ask a model too, the judge, and let the same failure out
as a Python traceback: dozens of lines, with the one that matters at the bottom.
A live calibration against a stub that was not running printed one (R11.23). It
is the same failure, and a person fixes it the same way: start the server, set
the variable, or correct the key. So it gets the same line.

A model fails in the ways `run` already catches: no endpoint is set for its
provider (R9.2 row 3), or a request is refused or never answered, after R9.17's
retries (R9.12 row 4). The line is the pipeline's name and then the error the
client raised. The client already names the URL and the status and never the key
(R9.8 row 1), and the command adds nothing to that.

Nothing else is turned into a line. An exception that is not a model's, such as
a bug, still prints its traceback. This rule is for a failure a person can act
on from one sentence, and hiding one nobody expected would make it harder to
find.

- **Kind:** deterministic
- **Layer:** cli (`dossier.cli.main`)
- **Proved by:** `tests/acceptance/test_R009_20__a_model_that_fails_stops_a_command_in_one_line.py`
- **Status:** NOT MET

| # | Given | Then |
|---|-------|------|
| 1 | `dossier calibrate incident-audit --gold gold/incidents`, the judge at `http://localhost:8080/api` with nothing listening | `incident-audit: POST http://localhost:8080/api/chat/completions failed: ... (after 3 attempts)` on standard error, exit 2, and no traceback; no file under `calibrations/` |
| 2 | `dossier eval incident-audit --gold gold/incidents`, a `root_cause` verdict not in the cache, and the judge answering `401` | `incident-audit: POST http://localhost:8080/api/chat/completions answered 401 Unauthorized`, and exit 2; the key is not in it (R9.8 row 1) |
| 3 | `dossier eval incident-audit --gold gold/incidents --compare 20260806T142203Z-4f1a 20260907T090000Z-bbbb`, nothing listening | the line of row 1, and exit 2 |
| 4 | `dossier calibrate` of a pipeline whose `model:` is `hf:Qwen/Qwen2.5-7B-Instruct@1c0f8e6b`, with `DOSSIER_HF_URL` unset | `incident-audit: DOSSIER_HF_URL is not set, ...`, naming the variable, and exit 2 |
| 5 | `dossier run incident-audit`, nothing listening | the line of row 1, and exit 2 -- already true, and now stated |
| 6 | *counter-example* — `dossier eval`, every verdict served from the cache, nothing listening | completes, exit 0: no judge is asked (R7.18), so no model can fail it |
| 7 | *counter-example* — an exception that is not a model's, raised while the judge is asked | its traceback, as before: only a failure a person can act on from the line is turned into one |
