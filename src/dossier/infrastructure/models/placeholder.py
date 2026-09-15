"""What a provider's entry point resolves to until its client is written.

`anthropic` is registered so that a pipeline naming it loads (R9.1) -- every
pipeline in the fixtures names `anthropic`. Building a client for it fails with a
message that says so until Anthropic's own API gets a rule. Every other shipped
provider has a client: `openai`, `gemini` and `hf` (R9.12), and `ollama`
(R9.13).

It already states where its provider is reached by default, from spec 009's
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
