"""What a provider's entry point resolves to until its client is written.

`anthropic`, `ollama` and `hf` are registered now so that a pipeline naming
them loads (R9.1) -- every pipeline in the fixtures names `anthropic`. Building a
client for one fails exactly as it did before providers were registered, with a
message that says so, until R9.2 wires the OpenAI-compatible client in and the
Anthropic client follows.
"""

from __future__ import annotations


def not_wired(model_id: str):
    """Refuse to build a client that does not exist yet, naming the model."""
    raise NotImplementedError(
        f"no model client is wired up yet for {model_id!r}. "
        "`--plan` does not need one; executing a run will."
    )
