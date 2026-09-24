"""R9.17 — a model request answered 408, 409, 429 or 5xx, or not answered at all,
is sent again up to twice before it fails.

Observed from the CLI, because what a person sees is whether their run finished.
Before this rule one `429` from the endpoint the project uses by default --
Gemini behind a local OpenWebUI -- stopped `dossier run` at the document it hit,
with exit 2. No single component makes the rule true: the decision about which
answers are worth another request and how long to wait is the domain's, sending
it again is the model client's, and the stage above both must still see one
answer and count one call.

The provider is registered the way an installed package would register it
(R9.1), and builds the real OpenAI-compatible client over a transport that
answers from a script. The wait is handed to the client rather than taken, so
a test that is about waiting three seconds takes none. Nothing opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tests.fakes import register_provider
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
MODEL = "gemini:gemini-3.5-flash-lite"
OPENWEBUI = "http://localhost:8080/api"
KEY = "sk-4f1a"
FIELDS = ("loss_amount", "resolution_date", "severity", "affected_systems", "root_cause")
# The fixture folder holds three documents, so an unrefused run is three POSTs.
DOCUMENTS = 3


def _abstaining() -> str:
    """An answer valid for any document: every field abstains (R6.5).

    This rule is about whether the answer arrives, not what it says.
    """
    return json.dumps(
        {
            "document": "any",
            "fields": [
                {"field": field, "value": None, "reason": "not stated in document"}
                for field in FIELDS
            ],
        }
    )


class Server:
    """OpenWebUI's OpenAI-compatible route: the scripted answers first, then 200s.

    Every POST is remembered, because the rows are claims about how many were
    sent and whether the second is the same request as the first.
    """

    def __init__(self, *script: httpx.Response) -> None:
        self.script = list(script)
        self.posts: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        if self.script:
            return self.script.pop(0)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": _abstaining()}}]},
        )


@pytest.fixture
def waits() -> list[float]:
    """Every wait the client asked for, in order, instead of waiting."""
    return []


def _serve(monkeypatch, server: Server, waits: list[float]) -> None:
    """Register `gemini` as a package would, reaching `server` and never sleeping."""
    from dossier.infrastructure.models.openai_compatible import gemini

    def factory(model_id: str, *, url: str, api_key: str | None = None):
        return gemini(
            model_id,
            url=url,
            api_key=api_key,
            transport=httpx.MockTransport(server),
            sleep=waits.append,
        )

    register_provider(monkeypatch, "gemini", factory, default_url=OPENWEBUI)
    monkeypatch.setenv("DOSSIER_GEMINI_URL", OPENWEBUI)
    monkeypatch.setenv("DOSSIER_GEMINI_API_KEY", KEY)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _synced(workspace: Path, monkeypatch) -> None:
    write_pipeline(workspace, model=MODEL)
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output


class TestARateLimitedModelRequestIsSentAgain:
    """R9.17 — a model request answered 408, 409, 429 or 5xx, or not answered at
    all, is sent again up to twice before it fails."""

    def test_a_run_rate_limited_once_finishes(
        self, workspace: Path, monkeypatch, waits: list[float]
    ):
        """Example 1: the one where the endpoint answers 429 once, then 200."""
        server = Server(httpx.Response(429, json={"error": {"message": "slow down"}}))
        _serve(monkeypatch, server, waits)
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        # One more POST than documents: the refused one, sent again.
        assert len(server.posts) == DOCUMENTS + 1
        assert server.posts[0].content == server.posts[1].content
        assert "extract: 3 document(s) · 0 from cache · 0 failed" in result.output

    def test_the_server_says_how_long_to_wait(
        self, workspace: Path, monkeypatch, waits: list[float]
    ):
        """Example 2: the one where the 429 carries `Retry-After: 3`."""
        server = Server(httpx.Response(429, headers={"Retry-After": "3"}))
        _serve(monkeypatch, server, waits)
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert waits == [3.0]

    def test_three_refusals_fail_the_run_naming_the_attempts(
        self, workspace: Path, monkeypatch, waits: list[float]
    ):
        """Example 3: the one where the endpoint answers 503 three times."""
        server = Server(*(httpx.Response(503) for _ in range(3)))
        _serve(monkeypatch, server, waits)
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert len(server.posts) == 3
        # 0.5 s and then 1 s, each shortened by up to a quarter at random.
        assert len(waits) == 2
        assert 0.375 <= waits[0] <= 0.5
        assert 0.75 <= waits[1] <= 1.0
        assert f"{OPENWEBUI}/chat/completions" in result.output
        assert "503" in result.output
        assert "3 attempts" in result.output
        assert KEY not in result.output

    def test_a_refused_key_is_not_sent_again(
        self, workspace: Path, monkeypatch, waits: list[float]
    ):
        """Example 7, a counter-example: the one where the endpoint answers 401."""
        server = Server(httpx.Response(401, json={"error": {"message": "denied"}}))
        _serve(monkeypatch, server, waits)
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert len(server.posts) == 1
        assert waits == []
        assert KEY not in result.output
