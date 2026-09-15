"""What a provider's entry point resolves to until its client is written.

`anthropic`, `ollama` and `hf` are registered now so that a pipeline naming
them loads (R9.1) -- every pipeline in the fixtures names `anthropic`. Building a
client for one fails with a message that says so, until a real client replaces
its placeholder.

Each already states where its provider is reached by default, from spec 009's
table: the endpoint is looked up before the client is built (R9.2), and a
provider's default is the provider's to declare.
"""

from __future__ import annotations


class NotWired:
    """A provider that is registered and has no client yet."""

    def __init__(self, default_url: str | None) -> None:
        self.default_url = default_url

    def __call__(self, model_id: str, *, url: str, api_key: str | None = None):
        raise NotImplementedError(
            f"no model client is wired up yet for {model_id!r}. "
            "`--plan` does not need one; executing a run will."
        )


anthropic = NotWired("https://api.anthropic.com")
openai = NotWired("https://api.openai.com/v1")
gemini = NotWired("https://generativelanguage.googleapis.com/v1beta/openai")
ollama = NotWired("http://localhost:11434")
# vLLM has no default: a run that needs it stops, naming DOSSIER_HF_URL (R9.2).
hf = NotWired(None)
