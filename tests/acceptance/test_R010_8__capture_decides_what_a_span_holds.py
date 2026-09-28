"""R10.8 — `DOSSIER_MLFLOW_CAPTURE` decides whether a span carries document text or
only its hashes. The CLI half.

The unit test beside this one proves what `span_payload` *returns*. This one
proves a `dossier run` *records* it -- the rule's Given -- because `/verify`
found `capture` and `span_payload` with no caller anywhere in `src/`: the
variable in spec 010's table was read nowhere, and every LLM span held the
model identifier and the attempt count whatever it was set to. The same shape
as `is_stale` before R7.15 and `record_eval` before #152: a rule fully proved
one layer below the thing it promises.

Tracking is switched on the way a person switches it on, in the environment
(R10.1), and the CLI is handed a `FakeTracker` through the same seam as
`build_model_client`. The four incidents are `_fixtures.md`'s scoring example.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.domain.hashing import text_hash

URI = "http://localhost:5000"
SHA256 = re.compile(r"[0-9a-f]{64}")


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def tracker(workspace: Path, monkeypatch) -> FakeTracker:
    """The four incidents held, then tracking switched on and recording to a fake."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


def _run(workspace: Path, monkeypatch, model):
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return _cli(workspace, monkeypatch, "run", PIPELINE)


def _llm_span_for(tracker: FakeTracker, document: str) -> dict:
    """The one LLM span in `document`'s extract trace."""
    traces = [t for t in tracker.runs[0].traces if t.tags["dossier.document"] == document]
    assert len(traces) == 1, traces
    spans = [span for span in traces[0].spans if span["kind"] == "llm"]
    assert len(spans) == 1, spans
    return spans[0]


class TestCaptureDecidesWhatASpanHolds:
    """R10.8 — `DOSSIER_MLFLOW_CAPTURE` decides whether a span carries document text
    or only its hashes."""

    def test_unset_records_the_rendered_prompt_and_the_reply(
        self, workspace: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where nothing is set, so the span holds the text.

        `full` is the default: the rendered prompt, which contains the document,
        and the model's reply, word for word.
        """
        model = RoutedModel(ANSWERS)

        result = _run(workspace, monkeypatch, model)

        assert result.exit_code == 0, result.output
        span = _llm_span_for(tracker, "INC-4821")
        assert "# INC-4821\n" in span["prompt"], "the rendered prompt holds the document"
        assert span["reply"] == json.dumps(
            {"document": "INC-4821", "fields": ANSWERS["INC-4821"]}
        )

    def test_hashes_records_the_hashes_and_no_text(
        self, workspace: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where the span says what was asked and holds no word of it.

        The prompt template's hash, the hash of each input the stage read, and
        the cache key: anyone with the documents can check them, and nobody with
        only the server can read them.
        """
        monkeypatch.setenv("DOSSIER_MLFLOW_CAPTURE", "hashes")

        result = _run(workspace, monkeypatch, RoutedModel(ANSWERS))

        assert result.exit_code == 0, result.output
        span = _llm_span_for(tracker, "INC-4821")
        prompt = workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"
        assert span["prompt_hash"] == text_hash(prompt)
        assert span["input_hashes"] and all(SHA256.fullmatch(h) for h in span["input_hashes"])
        assert SHA256.fullmatch(span["key"])
        assert "prompt" not in span and "reply" not in span
        assert not any(
            "INC-4821" in str(value) for name, value in span.items() if name != "dossier.model"
        ), "no document text under `hashes`"

    def test_an_unknown_value_is_refused_before_any_work(
        self, workspace: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one where `none` is neither `full` nor `hashes`.

        Read as `full` it would copy text the person meant to keep out of the
        server; read as `hashes` it would be a guess. So neither, and before a
        single model call.
        """
        monkeypatch.setenv("DOSSIER_MLFLOW_CAPTURE", "none")
        model = RoutedModel(ANSWERS)

        result = _run(workspace, monkeypatch, model)

        assert result.exit_code == 2, result.output
        assert "DOSSIER_MLFLOW_CAPTURE" in result.output
        assert "full" in result.output and "hashes" in result.output
        assert model.call_count == 0
        assert tracker.runs == []

    def test_identity_is_recorded_under_both_values(
        self, workspace: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 4): the one where what identifies a call is kept either way.

        The model identifier and the attempt count say which work the span was
        and disclose nothing, so `hashes` keeps them.
        """
        monkeypatch.setenv("DOSSIER_MLFLOW_CAPTURE", "hashes")

        result = _run(workspace, monkeypatch, RoutedModel(ANSWERS))

        assert result.exit_code == 0, result.output
        span = _llm_span_for(tracker, "INC-4821")
        assert span["dossier.model"] == RoutedModel.model_id
        assert span["dossier.attempt"] == 1
