"""R3.8 — loading a valid configuration performs no network I/O and no model calls.

Loading is a pure function of files on disk. It is also the step that runs before
every other step, so anything expensive here is paid on every command.

The network is stubbed to count and refuse, rather than only refused: the autouse
`no_network` fixture would fail a load that reached out, but a count of zero is
the claim, and the counter-example needs the same count to be non-zero.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from tests.fakes import register_connector, register_provider
from tests.pipelines import write_pipeline

from dossier.config.load import load_pipeline, load_sources
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.infrastructure.connectors.folder import FolderKeys
from dossier.infrastructure.models.registry import available_providers

PIPELINE = "incident-audit"

# The types these examples use, and the keys each declares (R1.10). No Jira
# connector ships in dossier; `None` stands in for one declaring no keys beyond
# the shared ones, which is all these examples give it.
CONNECTORS = {"folder": FolderKeys, "jira": None}

SOURCES = """\
sources:
  - id: incidents-jira
    type: jira
    fields: [key, summary, status]
  - id: incidents-manual
    type: folder
    path: inbox/incidents/
"""


class Network:
    """Every connection attempted, each one refused."""

    def __init__(self) -> None:
        self.attempts: list[object] = []

    def refuse(self, *args, **kwargs):
        self.attempts.append(args[0] if args else None)
        raise ConnectionRefusedError("the network is stubbed to raise")


@pytest.fixture
def network(monkeypatch) -> Network:
    stub = Network()
    monkeypatch.setattr(socket, "socket", stub.refuse)
    monkeypatch.setattr(socket, "create_connection", stub.refuse)
    return stub


def _configuration(workspace: Path) -> tuple[Path, Path]:
    """A valid `sources.yaml` and `pipeline.yaml`, the tracker and the fixture folder."""
    sources = workspace / "sources.yaml"
    sources.write_text(SOURCES, encoding="utf-8")
    pipeline = write_pipeline(workspace, sources=["incidents-jira", "incidents-manual"])
    return sources, pipeline


class IssueTracker:
    """A Jira stand-in whose fetch goes over the network, as a real one's does."""

    media_type = "application/json"

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        yield ItemRef(key="INC-4821", remote_version="v1", updated_at=None)

    def fetch(self, key: str) -> RawItem:
        socket.create_connection(("issues.example.internal", 443))
        raise AssertionError("unreachable: the network is stubbed to raise")

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


class TestConfigLoadingTouchesNothingExternal:
    """R3.8 — loading a valid configuration performs no network I/O and no model calls."""

    def test_a_valid_configuration_loads_with_the_network_refusing(
        self, workspace: Path, network: Network
    ):
        """Example 1: the one loaded with the network stubbed to raise."""
        sources, pipeline = _configuration(workspace)

        loaded = load_sources(sources, connectors=CONNECTORS)
        config = load_pipeline(pipeline, providers=available_providers())

        assert [source.id for source in loaded] == ["incidents-jira", "incidents-manual"]
        assert config.name == PIPELINE
        assert network.attempts == []

    def test_a_valid_configuration_loads_with_the_model_client_refusing(
        self, workspace: Path, monkeypatch
    ):
        """Example 2: the one with the model client stubbed to raise on any call.

        The provider is registered the way an installed package would be, and
        building its client raises. Loading asks which providers exist -- names
        only -- and never builds one, so it never finds out.
        """
        built: list[str] = []

        def refusing_client(model_id: str, **endpoint):
            built.append(model_id)
            raise AssertionError("loading built a model client")

        register_provider(monkeypatch, "anthropic", refusing_client)
        _, pipeline = _configuration(workspace)

        config = load_pipeline(pipeline, providers=available_providers())

        assert config.model == "anthropic:claude-sonnet-4-5-20250929"
        assert built == []

    def test_a_jira_source_loads_without_its_credentials(self, workspace: Path, monkeypatch):
        """Example 3: the one declaring `type: jira` with `JIRA_TOKEN` unset.

        Credentials are checked when a connector is used, not when config is
        read (R1.8): a missing token found at load would stop `dossier plan`,
        which never reaches Jira at all.
        """
        monkeypatch.delenv("JIRA_TOKEN", raising=False)
        sources, _ = _configuration(workspace)

        (tracker, _folder) = load_sources(sources, connectors=CONNECTORS)

        assert tracker.type == "jira"

    def test_sync_after_loading_does_reach_the_network(
        self, workspace: Path, monkeypatch, network: Network
    ):
        """Counter-example (row 4): the one running `dossier sync` right after loading.

        It reaches the network, as it must: the rule constrains loading, not the
        command containing it. Without this row, a test proving zero attempts
        would pass just as well against a stub that could never connect at all.
        """
        from typer.testing import CliRunner

        from dossier.cli.main import app

        _configuration(workspace)
        register_connector(monkeypatch, "jira", lambda config, *, workspace: IssueTracker())
        monkeypatch.chdir(workspace)

        result = CliRunner().invoke(app, ["sync", PIPELINE])

        assert network.attempts == [("issues.example.internal", 443)]
        assert result.exit_code == 1
        assert "INC-4821" in result.output
