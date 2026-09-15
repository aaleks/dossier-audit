"""What a provider's entry point resolves to until its client is written.

`anthropic` and `ollama` are registered so that a pipeline naming them loads
(R9.1) -- every pipeline in the fixtures names `anthropic`. Building a client for
one fails with a message that says so, until a real client replaces its
placeholder: Anthropic has its own API, and Ollama is reached through its native
one, and each is a later rule. `openai`, `gemini` and `hf` have theirs (R9.12).

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
ollama = NotWired("http://localhost:11434")
