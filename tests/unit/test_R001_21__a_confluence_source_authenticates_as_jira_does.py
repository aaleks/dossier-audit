"""R1.21 — a Confluence source authenticates as a Jira source does.

`token_env` alone means Bearer, `user_env` beside it means Basic, and neither
means anonymous. A user with no token is refused at load time (R1.12). Data
Center takes a personal access token as Bearer, and Cloud takes an API token only
as Basic, `email:token`. One function decides the header for both connectors, so
the two cannot drift apart.

Every request goes through an `httpx.MockTransport` that records its headers,
the export's redirect included. No socket is opened.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

import dossier.infrastructure.connectors.confluence as confluence
import dossier.infrastructure.connectors.jira as jira
from dossier.config.credentials import credential_for
from dossier.config.load import ConfigError, load_sources
from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.connectors.atlassian import authorization
from dossier.infrastructure.connectors.confluence import ConfluenceConnector, ConfluenceKeys

BASE = "https://confluence.example.internal"
PAGE = "81920114"
TOKEN = "confluence-pat-81920114-do-not-print"
USER = "a.aleks@example.internal"
TOKEN_VARIABLE = "DOSSIER_CONFLUENCE_TOKEN"
USER_VARIABLE = "DOSSIER_CONFLUENCE_USER"
EXPORT_FILE = "/download/export/pdfexport-1/OPS-114.pdf"


class Recorder:
    """Confluence, answering every read and remembering each request's `Authorization`."""

    def __init__(self) -> None:
        self.headers: dict[str, str | None] = {}

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            self.headers[path] = request.headers.get("authorization")
            if path == "/rest/api/content/search":
                page = {"id": PAGE, "type": "page", "version": {"number": 37}}
                return httpx.Response(200, json={"results": [page], "_links": {}})
            if path == f"/rest/api/content/{PAGE}":
                return httpx.Response(200, json={"id": PAGE, "version": {"number": 37}})
            if path == f"/rest/api/content/{PAGE}/child/attachment":
                matrix = {
                    "id": "81920301",
                    "title": "escalation-matrix.png",
                    "version": {"number": 2},
                    "_links": {
                        "download": f"/download/attachments/{PAGE}/escalation-matrix.png"
                    },
                }
                return httpx.Response(200, json={"results": [matrix], "_links": {}})
            if path.startswith(f"/download/attachments/{PAGE}/"):
                return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n")
            if path == "/spaces/flyingpdf/pdfpageexport.action":
                return httpx.Response(302, headers={"location": EXPORT_FILE})
            if path == EXPORT_FILE:
                return httpx.Response(200, content=b"%PDF-1.5\n")
            return httpx.Response(404)

        return httpx.MockTransport(handle)


class Built(ConfluenceConnector):
    """`ConfluenceConnector` as `from_config` builds it, over a recording transport."""

    recorder: Recorder

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs, transport=self.recorder.transport())


def source(**keys: str) -> SourceConfig:
    options = {"url": BASE, "query": "space = OPS", "export": "pdf", **keys}
    return SourceConfig(id="procedures-confluence", type="confluence", options=options)


def every_request(config: SourceConfig, environ: dict[str, str], tmp_path: Path) -> set:
    """The `Authorization` on each read: listing, files, page, file, export, its file."""
    recorder = Recorder()
    factory = type("Built", (Built,), {"recorder": recorder})
    connector = factory.from_config(
        config, workspace=tmp_path, credential=credential_for(config, environ=environ)
    )
    list(connector.list(None))
    list(connector.attachments(PAGE))
    connector.fetch(PAGE)
    connector.fetch(f"{PAGE}/escalation-matrix.png")
    connector.fetch(f"{PAGE}.pdf")
    assert EXPORT_FILE in recorder.headers, "the export's redirect was never followed"
    assert len(recorder.headers) == 6
    return set(recorder.headers.values())


class TestAConfluenceSourceAuthenticatesAsJiraDoes:
    """R1.21 — the header follows the keys, as it does for Jira."""

    def test_a_token_alone_is_sent_as_bearer_everywhere(self, tmp_path: Path):
        """Example 1: the one where only `token_env` is named, the export included."""
        config = source(token_env=TOKEN_VARIABLE)

        headers = every_request(config, {TOKEN_VARIABLE: TOKEN}, tmp_path)

        assert headers == {f"Bearer {TOKEN}"}

    def test_a_user_beside_the_token_is_sent_as_basic(self, tmp_path: Path):
        """Example 2: the one where `user_env` is named beside `token_env`."""
        config = source(token_env=TOKEN_VARIABLE, user_env=USER_VARIABLE)
        expected = "Basic " + base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()

        headers = every_request(config, {TOKEN_VARIABLE: TOKEN, USER_VARIABLE: USER}, tmp_path)

        assert headers == {expected}

    def test_no_keys_means_no_authorization_header(self, tmp_path: Path):
        """Counter-example, row 3: the one where `cwiki.apache.org` is read anonymously."""
        headers = every_request(source(), {}, tmp_path)

        assert headers == {None}

    def test_a_user_without_a_token_is_refused_at_load_time(self, tmp_path: Path):
        """Counter-example, row 4: the one where half a credential is named."""
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n"
            "  - id: procedures-confluence\n"
            "    type: confluence\n"
            f"    url: {BASE}\n"
            "    query: space = OPS\n"
            f"    user_env: {USER_VARIABLE}\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors={"confluence": ConfluenceKeys})

        message = str(error.value)
        assert "procedures-confluence" in message
        assert "user_env" in message and "token_env" in message

    def test_one_function_decides_the_header_for_both_connectors(self):
        """The one where Jira and Confluence cannot drift apart."""
        assert jira.authorization is authorization
        assert confluence.authorization is authorization
