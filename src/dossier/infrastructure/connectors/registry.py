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
    """

    def __call__(self, config: SourceConfig, *, workspace: Path) -> Connector: ...


class UnknownSourceType(Exception):
    """No installed package provides a connector for this source type."""


def available_types() -> list[str]:
    """Every source type an installed package provides, sorted."""
    return sorted(point.name for point in entry_points(group=ENTRY_POINT_GROUP))


def build_connector(config: SourceConfig, *, workspace: Path) -> Connector:
    """The connector for one source, resolved through the entry point group."""
    for point in entry_points(group=ENTRY_POINT_GROUP):
        if point.name == config.type:
            factory: ConnectorFactory = point.load()
            return factory(config, workspace=workspace)

    known = available_types()
    raise UnknownSourceType(
        f"source {config.id!r} has type {config.type!r}, which no installed package "
        f"provides. Available: {known or 'none'}. A source type is added by "
        f"installing a package that declares a {ENTRY_POINT_GROUP} entry point."
    )
