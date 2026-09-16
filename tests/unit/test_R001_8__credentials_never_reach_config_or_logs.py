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

from dossier.config.load import ConfigError, load_sources
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

pytestmark = pytest.mark.outer_loop

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


def credential_for(source, environ):
    """`dossier.config.credentials.credential_for`, imported where it is used.

    At module level the import fails while the rule is open, and a failed import
    is a failed collection -- which turns the default suite red for everyone.
    The `outer_loop` marker deselects tests; it does not stop pytest importing
    the module they are in.
    """
    from dossier.config.credentials import credential_for as resolve

    return resolve(source, environ=environ)


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
        credential = credential_for(source, {VARIABLE: TOKEN})

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
        credential = credential_for(source, {VARIABLE: TOKEN})

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
        credential = credential_for(source, {VARIABLE: TOKEN})

        report = sync(tmp_path, IssueTracker(credential), source)

        written = [item for item in tmp_path.rglob("*") if item.is_file()]
        assert report.failed == ()
        assert written, "the sync wrote nothing, so the search below would prove nothing"
        assert [item for item in written if TOKEN.encode() in item.read_bytes()] == []
        with Ledger(tmp_path) as ledger:
            (row,) = ledger.rows("incidents-jira")
        assert TOKEN not in repr(row)
