"""R10.7 — no credential's value reaches a tracking record.

R9.8's promise, for MLflow. A tracking server may be shared more widely than the
keys a machine holds, so a key that reached a param, a tag, a span or an
artifact would be disclosed to everyone who can read the experiment. A key
travels only as far as the request header it is sent in.

`execute` runs with a real Gemini client whose key is set, answered by
`httpx.MockTransport` -- no socket is opened -- and a `FakeTracker` holding
everything the run recorded, which is then searched for the key's value.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from tests.fakes import FakeTracker
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import RunInputs, RunRecording, execute
from dossier.config.endpoints import EndpointUnset, endpoint_for
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.models.openai_compatible import ModelRequestFailed, gemini

KEY = "sk-4f1a-do-not-record"
GEMINI = "gemini:gemini-3.5-flash-lite"
OPENWEBUI = "http://localhost:8080/api"
DOCUMENT = "INC-4821"


def _config(model: str) -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-jira"],
        model=model,
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/extract.md",
                input="documents",
                mode="per_file",
                output="schemas/incident.yaml",
            )
        ],
    )


def _openwebui(status: int) -> httpx.MockTransport:
    """OpenWebUI's OpenAI-compatible route, answering with `status`."""
    answer = json.dumps(
        {
            "document": DOCUMENT,
            "fields": [
                {"field": "loss_amount", "value": None, "reason": "not stated in document"}
            ],
        }
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"detail": "Not authenticated"})
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    return httpx.MockTransport(handle)


def _execute(workspace: Path, model, tracker: FakeTracker) -> None:
    execute(
        RunInputs(
            pipeline=_config(model.model_id),
            pipeline_hash="6e0d4b27" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents={DOCUMENT: "a3f9c1e2" * 8},
            document_text={DOCUMENT: ISSUES[DOCUMENT]},
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
        recording=RunRecording(tracker=tracker, experiment="dossier-audit/incident-audit/run"),
    )


def _llm_spans(tracker: FakeTracker) -> list[dict]:
    return [span for span in tracker.spans if span["kind"] == "llm"]


class TestNoCredentialReachesATrackingRecord:
    """R10.7 — no credential's value reaches a tracking record."""

    def test_a_recorded_run_holds_the_key_nowhere(self, tmp_path: Path):
        """Example 1: the one run with `DOSSIER_GEMINI_API_KEY` set.

        Every param, tag, metric, trace, span and artifact the run recorded is
        searched for the key's value, and it is in none of them.
        """
        tracker = FakeTracker()
        model = gemini(GEMINI, url=OPENWEBUI, api_key=KEY, transport=_openwebui(200))

        _execute(tmp_path, model, tracker)

        assert tracker.runs, "nothing was recorded, so the search below would prove nothing"
        assert KEY not in repr(tracker.runs)

    def test_a_refusal_is_a_span_naming_the_url_and_the_status_and_not_the_key(
        self, tmp_path: Path
    ):
        """Example 2: the one where OpenWebUI answers 401.

        The call happened and failed, so it is an LLM span, and the span says why
        -- by URL and status, as the error does (R9.8 row 1) -- without the key.
        """
        tracker = FakeTracker()
        model = gemini(GEMINI, url=OPENWEBUI, api_key=KEY, transport=_openwebui(401))

        with pytest.raises(ModelRequestFailed):
            _execute(tmp_path, model, tracker)

        refused = _llm_spans(tracker)
        assert len(refused) == 1
        error = str(refused[0].get("error"))
        assert f"{OPENWEBUI}/chat/completions" in error
        assert "401" in error
        assert KEY not in repr(tracker.runs)

    def test_naming_a_variable_on_a_span_is_not_disclosing_it(self, tmp_path: Path):
        """Counter-example (row 3): the one whose error names the variable to set.

        Allowed, and the useful thing to record: a variable's name is in
        `.env.example` for anyone to read. Only its value is a secret.
        """

        class Unreachable:
            """A model this machine has no endpoint for, as `hf` has none by default."""

            model_id = "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5

            def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
                endpoint_for("hf", default_url=None, environ={"DOSSIER_HF_API_KEY": KEY})
                return ""

        tracker = FakeTracker()

        with pytest.raises(EndpointUnset):
            _execute(tmp_path, Unreachable(), tracker)

        named = _llm_spans(tracker)
        assert len(named) == 1
        assert "DOSSIER_HF_URL" in str(named[0].get("error"))
        assert KEY not in repr(tracker.runs)
