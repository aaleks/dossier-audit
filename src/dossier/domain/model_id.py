"""Whether a model identifier names an exact, immutable version (R0.6).

A floating alias is one a provider may re-point. A run keyed on it could be
answered by a different model next month under the same key, and nothing in the
cache would show it (R0.5). So the decision is made here, once, and refused
before any work begins -- the loader only adds where it was written (R3.4).
"""

from __future__ import annotations

import re

# An anthropic snapshot ends in its release date. The family name without it --
# `claude-sonnet-4-5` -- is an alias that moves to each new snapshot.
_DATED = re.compile(r"-\d{8}$")

# Undated ids the provider documents as fixed (R0.6 row 5). A date suffix is how
# most anthropic ids are pinned, not what pinned means. Each entry is a claim
# about a provider, and a wrong one is a floating alias let through -- so the
# list is short, and an entry is added only once someone has confirmed it.
_FIXED = frozenset({"anthropic:claude-opus-5"})

# An Ollama tag moves when the model is re-pulled; its digest does not. The tag
# only names what to ask the server for, so `ollama:qwen2.5:latest@sha256:...` is
# pinned and `ollama:qwen2.5:7b` is not (R9.3). All 64 lowercase hex characters,
# as every hash in dossier is (R0.7): a prefix could match more than one model.
_OLLAMA_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")

# An OpenAI snapshot ends in its release date, dashed: `gpt-4o-2024-08-06`. The
# family name alone, and any `-latest` name, is an alias OpenAI re-points at each
# release (R9.9). Anthropic's undashed `-YYYYMMDD` is a different provider's form
# and is not accepted as one here.
_OPENAI_DATED = re.compile(r"-\d{4}-\d{2}-\d{2}$")

# Google names a Gemini model three ways, and only the stable code is a pin. A
# `-latest` name is re-pointed at each release; preview and experimental names
# may be replaced under the same name (R9.10). Matched as whole `-`-separated
# words, so a code that merely contains the letters is not refused. Gemini
# reports no digest, so the pin rests on Google's documentation, as Anthropic's
# does.
_GEMINI_MOVING = re.compile(r"(^|-)(latest|preview|exp|experimental)(-|$)")

# A Hugging Face repository is whatever `main` points at today; a revision is a
# commit, and does not move (R9.5). `@main` looks like a pin and is not one, so
# only a full 40-character commit counts. vLLM does not report which revision
# it loaded -- this pin is declared, and R9.6 checks only the repository.
_HF_REVISION = re.compile(r"^[^/@\s]+/[^/@\s]+@[0-9a-f]{40}$")


def provider_of(model: str) -> str:
    """The provider a model identifier names: whatever precedes its first `:` (R9.1).

    The first, not the last: an Ollama tag keeps its own colon, so
    `ollama:qwen2.5:7b@sha256:...` is the `ollama` provider's.
    """
    return model.partition(":")[0]


def check_pinned(model: str) -> None:
    """Raise `ValueError` naming `model` if it is a floating alias."""
    if model in _FIXED:
        return
    provider, _, name = model.partition(":")
    if provider == "anthropic" and not _DATED.search(name):
        raise ValueError(
            f"model {model!r} is a floating alias; name a dated snapshot such as "
            "'anthropic:claude-sonnet-4-5-20250929'"
        )
    if provider == "openai" and not _OPENAI_DATED.search(name):
        raise ValueError(
            f"model {model!r} is an OpenAI alias, which moves to each new snapshot; "
            "name a dated snapshot such as 'openai:gpt-4o-2024-08-06'"
        )
    if provider == "gemini" and _GEMINI_MOVING.search(name):
        raise ValueError(
            f"model {model!r} is a latest, preview or experimental name, which Google "
            "may re-point or replace; name a stable code such as "
            "'gemini:gemini-3.5-flash-lite'"
        )
    if provider == "ollama" and not _OLLAMA_DIGEST.search(name):
        raise ValueError(
            f"model {model!r} is an Ollama tag with no digest, and a tag moves when "
            "the model is re-pulled. Pin it as 'ollama:<name>:<tag>@sha256:<digest>'"
        )
    if provider == "hf" and not _HF_REVISION.match(name):
        raise ValueError(
            f"model {model!r} names no fixed revision, and a repository or branch "
            "moves with every push. Pin it as 'hf:<org>/<repo>@<40-character commit>'"
        )
