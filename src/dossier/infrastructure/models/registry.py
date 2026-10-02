"""Finding the providers a model identifier may name (R9.1).

Resolution is by entry point, never by a match statement, for the reason
R1.7 gives for connectors: a `match provider` in the core would make every new
provider a change to code every existing pipeline depends on.
"""

from __future__ import annotations

from importlib.metadata import entry_points

ENTRY_POINT_GROUP = "dossier.models"
# Providers that answer with vectors (spec 018, R18.3), under the same prefixes.
EMBEDDING_ENTRY_POINT_GROUP = "dossier.embeddings"


class UnknownProvider(LookupError):
    """A model names a provider no installed package declares (R9.1)."""


def provider(name: str):
    """The client factory an installed package declares for provider `name`.

    Called as `factory(model_id, url=..., api_key=...)`, with the endpoint this
    machine reaches it at (R9.2). Its `default_url`, where it has one, is used
    when that endpoint is not set.
    """
    return _load(ENTRY_POINT_GROUP, name, "model provider", available_providers)


def available_providers() -> list[str]:
    """Every provider an installed package declares, sorted.

    Names only: nothing is imported and no client is built. Loading a pipeline
    asks this, and loading reaches no network and no model (R3.8, R0.19).
    """
    return sorted(point.name for point in entry_points(group=ENTRY_POINT_GROUP))


def embedding_provider(name: str):
    """The embedding client factory an installed package declares for provider `name`.

    Built as a chat client is: `factory(model_id, url=..., api_key=...)`, with
    the endpoint `DOSSIER_<PROVIDER>_URL` names or the factory's `default_url`
    (R9.2). The client it returns has `embed(texts)`.
    """
    return _load(
        EMBEDDING_ENTRY_POINT_GROUP, name, "embedding provider", available_embedding_providers
    )


def available_embedding_providers() -> list[str]:
    """Every embedding provider an installed package declares, sorted. Names only."""
    return sorted(point.name for point in entry_points(group=EMBEDDING_ENTRY_POINT_GROUP))


def _load(group: str, name: str, what: str, available):
    for point in entry_points(group=group):
        if point.name == name:
            return point.load()
    raise UnknownProvider(
        f"no installed package provides {what} {name!r}. "
        f"Available: {', '.join(available()) or 'none'}"
    )
