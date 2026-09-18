"""Finding the connector for a source type (R1.7).

Resolution is by entry point, never by a match statement. Adding a source type is
a package that declares one in the `dossier.connectors` group; it is never an
edit to a file under `src/dossier/`.

That is not tidiness. A `match source.type` in the core package means every new
connector is a change to code that every existing pipeline depends on, reviewed
and released together with it.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol

from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import Connector

ENTRY_POINT_GROUP = "dossier.connectors"


class ConnectorFactory(Protocol):
    """What an entry point in the group must resolve to.

    A callable taking the source's configuration and the workspace, because a
    connector's arguments are type-specific -- a folder needs a path, a Jira
    query needs a JQL string -- and the core package must not know which.

    `credential` is what the source is reached with, and a factory declares it
    only if it needs one. It is passed in rather than looked up: `dossier.config`
    is the only package that reads the environment, and a connector that went
    looking there itself would be a second place credentials come from (R1.8).

    Declaring it is optional, and that is load-bearing. A connector written
    against `(config, workspace)` -- every third-party one that exists -- must go
    on working untouched, because R1.7 is the claim that adding a connector needs
    no change to this package, and a contract that widened under them would make
    it false in the other direction.
    """

    def __call__(
        self, config: SourceConfig, *, workspace: Path, credential: object | None = None
    ) -> Connector: ...


class UnknownSourceType(Exception):
    """No installed package provides a connector for this source type."""


def available_types() -> list[str]:
    """Every source type an installed package provides, sorted."""
    return sorted(point.name for point in entry_points(group=ENTRY_POINT_GROUP))


def declared_keys() -> dict[str, type | None]:
    """Each installed source type, and the keys model its connector declares (R1.10).

    Read from a `keys` attribute on whatever the entry point resolves to; `None`
    for a connector that declares none, which then takes nothing beyond the
    shared keys. Loading an entry point imports its package and does nothing
    else -- no connection, no credential (R3.8, R1.8).
    """
    return {
        point.name: getattr(point.load(), "keys", None)
        for point in sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda p: p.name)
    }


def _takes_credential(factory: object) -> bool:
    """Whether this factory asked for a credential.

    Asked rather than assumed, so that a connector written against
    `(config, workspace)` keeps working: R1.7 says adding a connector needs no
    change to this package, and widening the call under existing connectors
    would break that from this side instead.

    A factory whose signature cannot be read -- a C callable, an exotic
    partial -- is called the old way. The narrower call is the safe default:
    it is the one every connector has always accepted.
    """
    import inspect

    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return False
    return "credential" in parameters


def build_connector(
    config: SourceConfig, *, workspace: Path, credential: object | None = None
) -> Connector:
    """The connector for one source, resolved through the entry point group.

    `credential` comes from the caller, which is the composition root: this
    package may not read the environment, and must not learn how to (R1.8).
    """
    for point in entry_points(group=ENTRY_POINT_GROUP):
        if point.name == config.type:
            factory: ConnectorFactory = point.load()
            if _takes_credential(factory):
                connector = factory(config, workspace=workspace, credential=credential)
            else:
                connector = factory(config, workspace=workspace)
            _require_declaration(connector, config)
            return connector

    known = available_types()
    raise UnknownSourceType(
        f"source {config.id!r} has type {config.type!r}, which no installed package "
        f"provides. Available: {known or 'none'}. A source type is added by "
        f"installing a package that declares a {ENTRY_POINT_GROUP} entry point."
    )


def _require_declaration(connector: object, config: SourceConfig) -> None:
    """Refuse a connector that has not said whether its listings are complete (R1.11).

    Sync subtracts held from listed only against a listing it knows to be
    complete, and `lists_everything` is the one case it cannot work out for
    itself. A missing declaration could be defaulted to "may be partial" and
    nothing would break -- which is exactly how a folder-like connector written
    outside this repository would keep every deleted file `active` for ever,
    the bug the declaration exists to close. Refused here, before the first
    `list`, as a converter declaring no version is refused where it is
    registered (R8.2 row 4).
    """
    if not isinstance(getattr(connector, "lists_everything", None), bool):
        raise ValueError(
            f"source {config.id!r} has type {config.type!r}, whose connector does not "
            "declare `lists_everything`. A connector says whether `list` returns "
            "everything whatever `since` it is passed (True for a folder, False for "
            "a source that narrows by change time); sync tombstones only against a "
            "listing it knows to be complete (R1.11, R2.21)."
        )
