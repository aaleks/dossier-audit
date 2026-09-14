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
