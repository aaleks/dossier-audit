"""R9.6 — a run stops before its first model call if the served model names a
different repository.

A stage key holds the identifier, not the endpoint (R5.3 row 4), so a vLLM
server started with a different model would answer under an unchanged key --
and the cache would keep its answers as if the pinned model had given them. The
repository is what vLLM reports, so that is what is checked, once, before the
first completion. The revision is declared, not verified: vLLM does not report
it (R9.5).

The decision is `check_served`, a pure function. The client asks vLLM what it
serves and hands the answer across; `httpx.MockTransport` answers without a
socket.
"""

from __future__ import annotations

import httpx
import pytest

from dossier.domain.model_id import check_served
from dossier.infrastructure.models.openai_compatible import ModelRequestFailed, hf

REPOSITORY = "Qwen/Qwen2.5-7B-Instruct"
# `_fixtures.md` writes the revision as 8 characters; a real commit carries 40.
PINNED = f"hf:{REPOSITORY}@" + "1c0f8e6b" * 5
URL = "http://gpu-01:8000/v1"
ANSWER = '{"document": "INC-4821", "fields": []}'


class VLLM:
    """A vLLM server serving one repository, counting what it is asked."""

    def __init__(self, serving: str) -> None:
        self.serving = serving
        self.listed = 0
        self.completions = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            self.listed += 1
            listed = [{"id": self.serving, "root": self.serving}]
            return httpx.Response(200, json={"object": "list", "data": listed})
        self.completions += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": ANSWER}}]})

    def client(self):
        return hf(PINNED, url=URL, api_key=None, transport=httpx.MockTransport(self))


class TestAVLLMServingAnotherRepoStopsTheRun:
    """R9.6 — the repository vLLM serves must be the one the identifier pins."""

    def test_the_pinned_repository_being_served_lets_the_run_proceed(self):
        """Example 1: the one where vLLM reports `Qwen/Qwen2.5-7B-Instruct`.

        Checked once for the client, not once per call: the model a server
        loaded does not change between two requests of one run.
        """
        check_served(PINNED, served={REPOSITORY})

        server = VLLM(serving=REPOSITORY)
        client = server.client()
        client.complete("x", schema=None)
        client.complete("y", schema=None)

        assert server.listed == 1
        assert server.completions == 2

    def test_another_repository_stops_the_run_naming_both_with_no_model_call(self):
        """Example 2: the one where vLLM was started with `Qwen/Qwen2.5-14B-Instruct`."""
        other = "Qwen/Qwen2.5-14B-Instruct"
        with pytest.raises(ValueError) as decided:
            check_served(PINNED, served={other})
        assert REPOSITORY in str(decided.value)
        assert other in str(decided.value)

        server = VLLM(serving=other)
        with pytest.raises(ModelRequestFailed) as stopped:
            server.client().complete("x", schema=None)

        assert REPOSITORY in str(stopped.value)
        assert other in str(stopped.value)
        assert server.completions == 0

    def test_the_right_repository_at_another_revision_is_not_detected(self):
        """Counter-example (row 3): the one where only the revision differs.

        vLLM reports which repository it loaded and not which revision, so the
        revision is declared, not verified (R9.5). Whoever starts vLLM with
        `--revision` is responsible for it matching.
        """
        check_served(f"hf:{REPOSITORY}@" + "e04b6d52" * 5, served={REPOSITORY})
