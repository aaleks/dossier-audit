"""R1.8 — credentials come from the environment, and never appear in config, logs,
ledger or manifest.

`sources.yaml` is committed to git. Anything written in it is public to everyone
with repository access, so a credential is not something a source may hold: it
names the variable to read, and the value is read from the environment when the
connector is actually used (R3.8).

R9.8 is the same promise for model endpoints, and it is already met. This is the
half for source connectors, and the pieces mirror it: a value object whose `repr`
does not show what it holds, and a search of every byte a completed sync wrote.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from dossier.config.credentials import credential_for
from dossier.config.load import ConfigError, load_sources
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

TOKEN = "jira-pat-4f1a-do-not-print"
VARIABLE = "JIRA_TOKEN"
URL = "https://jira.example.internal/rest/api/2/search"


class JiraKeys(BaseModel):
    """What a Jira source may say, as its connector declares it (R1.10).

    `token` is declared here deliberately: the point of row 1 is that the core
    refuses a literal credential in `sources.yaml` whatever a connector is
    willing to accept. A connector cannot opt its users into committing secrets.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = ""
    token: str = ""
    token_env: str = ""


def write_sources(workspace: Path, body: str) -> Path:
    path = workspace / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def load(path: Path):
    return load_sources(path, connectors={"jira": JiraKeys})


class Unauthorised(Exception):
    """What a connector raises when the source refuses it (R1.8 row 2)."""


class IssueTracker:
    """A tracker that needs a credential, and never puts it in what it raises or returns."""

    lists_everything = False

    def __init__(self, credential, *, refuse: bool = False) -> None:
        self.credential = credential
        self.refuse = refuse

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        yield ItemRef(key="INC-4821", remote_version="v37", updated_at=None)

    def fetch(self, key: str) -> RawItem:
        if self.refuse:
            raise Unauthorised(f"GET {URL} returned 401 Unauthorized")
        return RawItem(
            key=key,
            payload=b'{"key": "INC-4821", "summary": "Batch failed"}',
            media_type="application/json",
            remote_version="v37",
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


def sync(workspace: Path, connector, source):
    from dossier.application.sync import sync_source

    with Ledger(workspace) as ledger:
        return sync_source(
            config=source,
            connector=connector,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC),
        )


class TestCredentialsNeverReachConfigOrLogs:
    """R1.8 — the value comes from the environment and stays there."""

    def test_a_token_written_into_sources_yaml_is_refused(self, tmp_path: Path):
        """Example 1: the one where someone commits `token:` to `sources.yaml`.

        Refused at load time, naming the file and the key -- and not repeating
        the value, which is the one thing the message must not do. Refused even
        though this connector declares `token`: a file in git is the wrong place
        for a secret whatever the connector accepts.
        """
        path = write_sources(
            tmp_path,
            f"sources:\n  - id: incidents-jira\n    type: jira\n    token: {TOKEN}\n",
        )

        with pytest.raises(ConfigError) as error:
            load(path)

        message = str(error.value)
        assert "sources.yaml" in message
        assert "token" in message
        assert TOKEN not in message

    def test_the_refusal_suggests_a_variable_named_for_the_sources_type(self, tmp_path: Path):
        """Example 7: the one where a Confluence source writes its token down.

        The suggestion carries the source's type and the `DOSSIER_` prefix, so
        following it word for word works from `.env` too (row 6, R9.11 row 4).
        """
        path = write_sources(
            tmp_path,
            "sources:\n"
            "  - id: procedures-confluence\n"
            "    type: confluence\n"
            f"    token: {TOKEN}\n",
        )

        with pytest.raises(ConfigError) as error:
            load(path)

        message = str(error.value)
        assert "`token_env: DOSSIER_CONFLUENCE_TOKEN`" in message
        assert "JIRA" not in message
        assert TOKEN not in message

    def test_naming_the_variable_is_allowed(self, tmp_path: Path):
        """Counter-example (row 4): the one written as `token_env: JIRA_TOKEN`.

        Allowed, and the useful thing to write: it says what to set without
        disclosing anything. Only the value is a secret, and it is read from the
        environment when the connector is used.
        """
        path = write_sources(
            tmp_path,
            f"sources:\n  - id: incidents-jira\n    type: jira\n    token_env: {VARIABLE}\n",
        )

        (source,) = load(path)
        credential = credential_for(source, environ={VARIABLE: TOKEN})

        assert source.options["token_env"] == VARIABLE
        assert credential.value == TOKEN
        assert TOKEN not in repr(credential)
        assert TOKEN not in str(credential)

    def test_a_refusal_names_the_url_and_the_status_and_not_the_token(self, tmp_path: Path):
        """Example 2: the one where the tracker answers 401.

        What sync reports is what the source said went wrong -- the URL and the
        status. A failure message is read by a person and often pasted into a
        ticket, so it is exactly the place a credential must not appear (R2.13).
        """
        path = write_sources(
            tmp_path,
            f"sources:\n  - id: incidents-jira\n    type: jira\n    token_env: {VARIABLE}\n",
        )
        (source,) = load(path)
        credential = credential_for(source, environ={VARIABLE: TOKEN})

        report = sync(tmp_path, IssueTracker(credential, refuse=True), source)

        ((key, reason),) = report.failures
        assert key == "INC-4821"
        assert URL in reason and "401" in reason
        assert TOKEN not in reason

    def test_nothing_a_completed_sync_wrote_holds_the_token(self, tmp_path: Path):
        """Example 3: the one where the sync succeeds and the workspace is searched.

        Every byte of it: the ledger, every snapshot, and `sources.yaml` itself.
        A credential in any of them is a credential in git or in a backup.
        """
        path = write_sources(
            tmp_path,
            f"sources:\n  - id: incidents-jira\n    type: jira\n    token_env: {VARIABLE}\n",
        )
        (source,) = load(path)
        credential = credential_for(source, environ={VARIABLE: TOKEN})

        report = sync(tmp_path, IssueTracker(credential), source)

        written = [item for item in tmp_path.rglob("*") if item.is_file()]
        assert report.failed == ()
        assert written, "the sync wrote nothing, so the search below would prove nothing"
        assert [item for item in written if TOKEN.encode() in item.read_bytes()] == []
        with Ledger(tmp_path) as ledger:
            (row,) = ledger.rows("incidents-jira")
        assert TOKEN not in repr(row)


DOTENV_VARIABLE = "DOSSIER_JIRA_TOKEN"


def _sync_with_dotenv(workspace: Path, monkeypatch, *, variable: str, received: list):
    """`dossier sync` over a source naming `variable`, with `.env` alone holding it.

    Through the CLI rather than `credential_for` directly: rows 5 and 6 are
    claims about what the composition root reads the credential through, and a
    unit call with `environ=` handed in would prove only that the argument is
    honoured. The stub records the credential it was built with.
    """
    from tests.fakes import register_connector
    from tests.pipelines import write_pipeline
    from typer.testing import CliRunner

    from dossier.cli.main import app

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: incidents-jira\n    type: issues\n    token_env: {variable}\n",
        encoding="utf-8",
    )
    (workspace / ".env").write_text(f"{variable}={TOKEN}\n", encoding="utf-8")
    write_pipeline(workspace, sources=["incidents-jira"])
    monkeypatch.delenv(variable, raising=False)

    def factory(config, *, workspace, credential=None):
        received.append(credential)
        return IssueTracker(credential)

    register_connector(monkeypatch, "issues", factory, keys=JiraKeys)
    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, ["sync", "incident-audit"])


class TestACredentialIsReadThroughDotenv:
    """R1.8 rows 5 and 6 — `.env` is part of the environment a credential comes from."""

    def test_a_prefixed_variable_in_dotenv_reaches_the_connector(
        self, workspace: Path, monkeypatch
    ):
        """Example 5: the one where `.env` alone holds `DOSSIER_JIRA_TOKEN`.

        The shell does not set it, and the connector is handed the value all the
        same: a credential is read through the same environment an endpoint's
        key is (R9.11), so one file holds every per-machine value.
        """
        received: list = []

        result = _sync_with_dotenv(
            workspace, monkeypatch, variable=DOTENV_VARIABLE, received=received
        )

        assert result.exit_code == 0, result.output
        (credential,) = received
        assert credential.variable == DOTENV_VARIABLE
        assert credential.value == TOKEN
        assert TOKEN not in result.output

    def test_an_unprefixed_variable_in_dotenv_is_not_read(self, workspace: Path, monkeypatch):
        """Counter-example (row 6): the one where `JIRA_TOKEN` is written only in `.env`.

        Only `DOSSIER_` variables are read from `.env` (R9.11 row 4), so this
        one is unset as far as dossier can see. Refused by name, before the
        connector is built, and the value in the file never appears.
        """
        received: list = []

        result = _sync_with_dotenv(workspace, monkeypatch, variable=VARIABLE, received=received)

        assert result.exit_code == 2, result.output
        assert VARIABLE in result.output
        assert TOKEN not in result.output
        assert received == []
