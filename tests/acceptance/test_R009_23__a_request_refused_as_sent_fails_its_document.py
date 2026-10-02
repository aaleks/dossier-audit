"""R9.23 — a stage's request refused as sent, `400`, `413` or `422`, fails the
document it asked about, and the run goes on.

A prompt past the model's context window is refused `400`, by OpenAI, by
Anthropic, and by an OpenWebUI in front of either. Before this rule, any refusal
stopped the run, and every rerun stopped at the same document. Here the model is
the real OpenAI-compatible client, its requests answered by `httpx.MockTransport`
without a socket: each incident's scripted answer, and a refusal for `INC-4822`.
So the status is read where a real one is, and the document fails where a real
one would.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tests.acceptance.conftest import _cli
from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
)

URL = "http://localhost:8080/api"
COMPLETIONS = f"{URL}/chat/completions"
REFUSED = "INC-4822"
TOO_LONG = "This model's maximum context length is 128000 tokens"


class Endpoint:
    """An OpenWebUI that answers each incident as scripted, and refuses one."""

    def __init__(self, status: int, reason: str = TOO_LONG) -> None:
        self.status, self.reason = status, reason
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        prompt = "".join(
            message["content"] if isinstance(message["content"], str) else json.dumps(message)
            for message in sent["messages"]
        )
        (key,) = [key for key in ANSWERS if f"# {key}\n" in prompt]
        self.asked.append(key)
        if key == REFUSED:
            return httpx.Response(self.status, json={"error": {"message": self.reason}})
        answer = json.dumps({"document": key, "fields": ANSWERS[key]})
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": answer}}]}
        )


def _workspace(workspace: Path, monkeypatch, endpoint: Endpoint) -> Path:
    """The scoring example's four incidents, synced, and the model reached at `endpoint`."""
    import dossier.cli.bootstrap as cli
    from dossier.infrastructure.models.openai_compatible import OpenAICompatibleClient

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    client = OpenAICompatibleClient(
        "gemini:gemini-3.5-flash-lite",
        name="gemini",
        url=URL,
        transport=httpx.MockTransport(endpoint),
        sleep=lambda seconds: None,
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return workspace


def _failures(workspace: Path) -> list[dict]:
    (record,) = sorted((workspace / "runs").glob("*/failures.json"))[-1:]
    return json.loads(record.read_text(encoding="utf-8"))


class TestARequestRefusedAsSentFailsItsDocument:
    """R9.23 — the document fails, and the others are answered."""

    def test_the_refused_document_fails_and_the_run_goes_on(self, workspace: Path, monkeypatch):
        """Row 1 — the one past the context window, in a run of four."""
        endpoint = Endpoint(400)
        _workspace(workspace, monkeypatch, endpoint)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        reason = f"POST {COMPLETIONS} answered 400 Bad Request: {TOO_LONG}"
        assert result.exit_code == 1, result.output
        assert f"    extract failed on {REFUSED}: {reason}" in result.stderr.splitlines()
        assert sorted(endpoint.asked) == sorted(ANSWERS)
        assert _failures(workspace) == [
            {"step": "extract", "document": REFUSED, "part": None, "reason": reason}
        ]

    def test_the_next_run_asks_again_for_the_refused_document_alone(
        self, workspace: Path, monkeypatch
    ):
        """Row 2 — the one run again: the three are cached, the refusal was not."""
        endpoint = Endpoint(400)
        _workspace(workspace, monkeypatch, endpoint)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 1
        endpoint.asked.clear()

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 1, result.output
        assert endpoint.asked == [REFUSED]

    @pytest.mark.parametrize(
        ("status", "phrase"), [(413, "Request Entity Too Large"), (422, "Unprocessable Entity")]
    )
    def test_too_large_and_unprocessable_fail_the_document_too(
        self, workspace: Path, monkeypatch, status: int, phrase: str
    ):
        """Row 3 — the ones refused `413` and `422`, each with its own status."""
        _workspace(workspace, monkeypatch, Endpoint(status, reason="the request is too big"))

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 1, result.output
        assert (
            f"    extract failed on {REFUSED}: POST {COMPLETIONS} answered {status} {phrase}: "
            "the request is too big"
        ) in result.stderr.splitlines()

    @pytest.mark.parametrize(
        ("status", "phrase"),
        [(401, "Unauthorized"), (404, "Not Found"), (429, "Too Many Requests")],
    )
    def test_a_refusal_no_other_request_would_avoid_stops_the_run(
        self, workspace: Path, monkeypatch, status: int, phrase: str
    ):
        """Rows 4 and 5, counter-examples — a key, a model, an endpoint too busy now."""
        _workspace(workspace, monkeypatch, Endpoint(status, reason="no"))

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert f"answered {status} {phrase}" in result.stderr
        assert "failed on" not in result.stderr
