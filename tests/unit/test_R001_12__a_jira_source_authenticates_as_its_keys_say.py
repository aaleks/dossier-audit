"""R1.12 — a Jira source authenticates as its keys say: Bearer with a token alone,
Basic with a user beside it.

Data Center takes a personal access token as `Authorization: Bearer`. Cloud
takes an API token only as HTTP Basic, `email:token`, and Data Center takes a
username and password the same way. The scheme is decided by what the source
names -- `token_env` alone, or `user_env` beside it -- and never by trying one
form and then the other against a server that has just refused the first.

Every request goes through an `httpx.MockTransport` that records its headers.
No socket is opened.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

from dossier.config.credentials import Credential, CredentialUnset, credential_for
from dossier.config.load import ConfigError, load_sources
from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.connectors.jira import JiraConnector, JiraKeys, JiraRequestFailed

BASE = "https://jira.example.internal"
QUERY = "project = INC AND type = Incident"
TOKEN = "jira-pat-4f1a-do-not-print"
USER = "a.aleks@example.internal"
TOKEN_VARIABLE = "DOSSIER_JIRA_TOKEN"
USER_VARIABLE = "DOSSIER_JIRA_USER"

ISSUE = "INC-4821"


def issue_json(key: str) -> dict:
    return {
        "key": key,
        "fields": {
            "updated": "2026-07-30T09:14:00.000+0000",
            "attachment": [
                {
                    "id": "10021",
                    "filename": "report.pdf",
                    "mimeType": "application/pdf",
                    "content": f"{BASE}/secure/attachment/10021/report.pdf",
                }
            ],
        },
    }


class Recorder:
    """Jira, answering reads and remembering the `Authorization` on each."""

    def __init__(self, *, status: int = 200) -> None:
        self.status = status
        self.headers: list[str | None] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.headers.append(request.headers.get("authorization"))
            if self.status != 200:
                return httpx.Response(self.status, json={"errorMessages": ["refused"]})
            path = request.url.path
            if path.endswith("/rest/api/2/search"):
                return httpx.Response(
                    200, json={"startAt": 0, "total": 1, "issues": [issue_json(ISSUE)]}
                )
            if path.endswith(f"/rest/api/2/issue/{ISSUE}"):
                return httpx.Response(200, json=issue_json(ISSUE))
            if "/secure/attachment/" in path:
                return httpx.Response(200, content=b"%PDF-1.4\n")
            return httpx.Response(404, json={"errorMessages": [f"no route for {path}"]})

        return httpx.MockTransport(handle)


class Built(JiraConnector):
    """`JiraConnector` as `from_config` builds it, with a recording transport underneath.

    `from_config` constructs `cls`, so a subclass is how a test sees the
    connector the entry point would build without a second constructor.
    """

    recorder: Recorder

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs, transport=self.recorder.transport())


def every_request(connector: JiraConnector, recorder: Recorder) -> list[str | None]:
    """The `Authorization` each read carried: a listing, an attachment listing, two fetches."""
    list(connector.list(None))
    list(connector.attachments(ISSUE))
    connector.fetch(ISSUE)
    connector.fetch(f"{ISSUE}/report.pdf")
    assert len(recorder.headers) >= 4
    return recorder.headers


def source(**keys: str) -> SourceConfig:
    options = {"url": BASE, "query": QUERY, **keys}
    return SourceConfig(id="incidents-jira", type="jira", options=options)


def build(config: SourceConfig, credential, tmp_path: Path) -> tuple[JiraConnector, Recorder]:
    recorder = Recorder()
    factory = type("Built", (Built,), {"recorder": recorder})
    return factory.from_config(config, workspace=tmp_path, credential=credential), recorder


class TestAJiraSourceAuthenticatesAsItsKeysSay:
    """R1.12 — the header follows the keys, and only the keys."""

    def test_a_token_alone_is_sent_as_bearer(self, tmp_path: Path):
        """Example 1: the one where only `token_env` is named."""
        config = source(token_env=TOKEN_VARIABLE)
        credential = credential_for(config, environ={TOKEN_VARIABLE: TOKEN})

        connector, recorder = build(config, credential, tmp_path)

        assert set(every_request(connector, recorder)) == {f"Bearer {TOKEN}"}

    def test_a_user_beside_the_token_is_sent_as_basic(self, tmp_path: Path):
        """Example 2: the one where `user_env` is named beside `token_env`."""
        config = source(token_env=TOKEN_VARIABLE, user_env=USER_VARIABLE)
        credential = credential_for(
            config, environ={TOKEN_VARIABLE: TOKEN, USER_VARIABLE: USER}
        )
        expected = "Basic " + base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()

        connector, recorder = build(config, credential, tmp_path)

        assert set(every_request(connector, recorder)) == {expected}
        assert USER not in repr(credential) and TOKEN not in repr(credential)

    def test_an_unset_user_variable_is_refused_before_any_request(self):
        """Example 3: the one where `user_env` names a variable nobody set.

        Refused where the credential is read, naming the variable, exactly as
        an unset `token_env` is (R1.8). No connector is built, so no request
        can have gone out with half a credential.
        """
        config = source(token_env=TOKEN_VARIABLE, user_env=USER_VARIABLE)

        with pytest.raises(CredentialUnset) as error:
            credential_for(config, environ={TOKEN_VARIABLE: TOKEN})

        assert USER_VARIABLE in str(error.value)
        assert TOKEN not in str(error.value)

    def test_a_refused_bearer_is_reported_and_not_retried_as_basic(self):
        """Counter-example (row 4): the one where the server answers 401.

        One request, one refusal naming the URL and the status (R1.8 row 2).
        The token is not sent again in another form: a connector that probed
        would put the credential on the wire twice and make a 401 mean two
        things.
        """
        recorder = Recorder(status=401)
        connector = JiraConnector(
            base_url=BASE, query=QUERY, token=TOKEN, transport=recorder.transport()
        )

        with pytest.raises(JiraRequestFailed) as error:
            connector.fetch(ISSUE)

        assert recorder.headers == [f"Bearer {TOKEN}"]
        assert f"{BASE}/rest/api/2/issue/{ISSUE}" in str(error.value)
        assert "401" in str(error.value)
        assert TOKEN not in str(error.value)

    def test_a_user_without_a_token_is_refused_at_load_time(self, tmp_path: Path):
        """Counter-example (row 5): the one where `user_env` is named and `token_env` is not.

        Half a credential, refused by the connector's own declaration when
        `sources.yaml` is read (R1.10), naming the source and both keys.
        """
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n"
            "  - id: incidents-jira\n"
            "    type: jira\n"
            f"    url: {BASE}\n"
            f"    query: {QUERY}\n"
            f"    user_env: {USER_VARIABLE}\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors={"jira": JiraKeys})

        message = str(error.value)
        assert "incidents-jira" in message
        assert "user_env" in message and "token_env" in message

    def test_no_keys_means_no_authorization_header(self):
        """Counter-example (row 6): the one where the source names neither.

        A Jira open to anonymous reads is reached as such: no header, rather
        than an empty one a server would refuse for the wrong reason.
        """
        recorder = Recorder()
        connector = JiraConnector(base_url=BASE, query=QUERY, transport=recorder.transport())

        assert set(every_request(connector, recorder)) == {None}

    def test_from_config_hands_the_user_through(self, tmp_path: Path):
        """The one where the credential arrives already resolved.

        The connector reads nothing from the environment itself (R1.8): the
        user reaches it the way the token does, as an argument.
        """
        config = source(token_env=TOKEN_VARIABLE, user_env=USER_VARIABLE)
        credential = Credential(
            variable=TOKEN_VARIABLE, value=TOKEN, user=USER, user_variable=USER_VARIABLE
        )

        connector, recorder = build(config, credential, tmp_path)

        (header,) = set(every_request(connector, recorder))
        assert header is not None and header.startswith("Basic ")
