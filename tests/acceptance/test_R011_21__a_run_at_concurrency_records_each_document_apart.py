"""R11.21 — a run asking about several documents at once records each one's
trace holding only its own spans, and says how many it asked at once.

Observed from the CLI with tracking switched on the way a person switches it on
(R10.1). The CLI is handed a `FakeTracker` through `build_tracker`, and wraps it
in the real `BestEffortTracker` as it wraps MLflow's, so the counting R10.24
does is the production code's. The fake keeps a trace current in the thread
that opened it, as the port now promises: a fake that kept one for the process
could not tell a run that mixed its traces from one that did not.

The model passes every call through a `Gate` set for three, so all three
traces are open before any span is recorded. That is the moment a tracker with
one current trace sends every span to the last one opened.

The fixture inbox holds `INC-4821.md`, `INC-4822.md` and `audit-note.md`, in
that document order; they stand for the three incidents the spec's rows name.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from tests.fakes import FakePromptRegistry, FakeTracker, FakeVersionRegistry, Gate
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
URI = "http://localhost:5000"
DOCUMENTS = ("INC-4821.md", "INC-4822.md", "audit-note.md")
FIELDS = ("loss_amount", "resolution_date", "severity", "affected_systems", "root_cause")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TRACES = re.compile(r"^warning: (\d+) trace\(s\) could not be recorded$", re.MULTILINE)


class GatedModel:
    """A model whose calls pass through `gate`, abstaining for any document (R6.5).

    `refusing_once` names a document answered with something that is not JSON
    the first time it is asked, so it is valid on its second attempt (R6.2).
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self, gate: Gate, *, refusing_once: str | None = None) -> None:
        self.gate = gate
        self.refusing_once = refusing_once

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        document = re.search(r'<document key="([^"]+)">', prompt).group(1)
        self.gate.through(document)
        if document == self.refusing_once:
            self.refusing_once = None
            return "no JSON here"
        return json.dumps(
            {
                "document": document,
                "fields": [
                    {"field": field, "value": None, "reason": "not stated in document"}
                    for field in FIELDS
                ],
            }
        )


class LosesOneTrace(FakeTracker):
    """One of `document`'s own calls fails (R10.6), and the server does not hold
    that trace either (R10.24): the same trace lost two ways.

    The server's answer is given by place among the traces the run opened, as
    `MlflowTracker` gives it -- read off the order this fake saw them opened in,
    which is the order the wrapper must count them in too.
    """

    def __init__(self, document: str) -> None:
        super().__init__()
        self.document = document
        self.unrecorded_traces: frozenset[int] = frozenset()

    def span(self, *, kind: str, name: str, attributes) -> None:
        super().span(kind=kind, name=name, attributes=attributes)
        if kind == "llm" and self._trace.tags["dossier.document"] == self.document:
            raise RuntimeError("the server stopped answering")

    def end_run(self, *, status) -> None:
        super().end_run(status=status)
        self.unrecorded_traces = frozenset(
            place
            for place, trace in enumerate(self.traces)
            if trace.tags["dossier.document"] == self.document
        )


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _synced(workspace: Path, monkeypatch) -> Path:
    write_pipeline(workspace)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return workspace


def _tracked_run(workspace: Path, monkeypatch, tracker: FakeTracker, model, *flags: str):
    import dossier.cli.main as cli

    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_version_registry", lambda settings: FakeVersionRegistry())
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: FakePromptRegistry(), raising=False
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return _cli(workspace, monkeypatch, "run", PIPELINE, *flags)


def _llm_spans(trace) -> list[dict]:
    return [span for span in trace.spans if span["kind"] == "llm"]


class TestARunAtConcurrencyRecordsEachDocumentApart:
    """R11.21 — each trace holds only its own spans, and the run says how many it
    asked at once."""

    def test_each_trace_holds_its_own_documents_call(self, workspace: Path, monkeypatch):
        """Row 1: the one where all three traces are open before any span."""
        _synced(workspace, monkeypatch)
        tracker = FakeTracker()
        gate = Gate(expected=3, meet=3)

        result = _tracked_run(
            workspace, monkeypatch, tracker, GatedModel(gate), "--concurrency", "3"
        )

        assert result.exit_code == 0, result.output
        assert gate.most_at_once == 3
        assert sorted(trace.name for trace in tracker.traces) == [
            f"extract · {document}" for document in DOCUMENTS
        ]
        for trace in tracker.traces:
            (call,) = _llm_spans(trace)
            assert f'<document key="{trace.tags["dossier.document"]}">' in call["prompt"]

    def test_a_retried_document_holds_both_its_calls(self, workspace: Path, monkeypatch):
        """Row 2: the one where `INC-4822` is valid on its second attempt."""
        _synced(workspace, monkeypatch)
        tracker = FakeTracker()
        gate = Gate(expected=3, meet=3)

        result = _tracked_run(
            workspace,
            monkeypatch,
            tracker,
            GatedModel(gate, refusing_once="INC-4822.md"),
            "--concurrency",
            "3",
        )

        assert result.exit_code == 0, result.output
        calls = {
            trace.tags["dossier.document"]: len(_llm_spans(trace)) for trace in tracker.traces
        }
        assert calls == {"INC-4821.md": 1, "INC-4822.md": 2, "audit-note.md": 1}

    @pytest.mark.parametrize(("flags", "recorded"), [(("--concurrency", "3"), "3"), ((), "1")])
    def test_the_run_says_how_many_it_asked_at_once(
        self, workspace: Path, monkeypatch, flags, recorded
    ):
        """Row 3: `concurrency` among the run's params, and `1` when nothing sets it."""
        _synced(workspace, monkeypatch)
        tracker = FakeTracker()
        gate = Gate(expected=3, meet=int(recorded))

        result = _tracked_run(workspace, monkeypatch, tracker, GatedModel(gate), *flags)

        assert result.exit_code == 0, result.output
        (run,) = tracker.runs
        assert run.params["concurrency"] == recorded

    def test_a_trace_lost_two_ways_on_one_thread_is_counted_once(
        self, workspace: Path, monkeypatch
    ):
        """Row 4: the one where `INC-4822`'s span fails and the server does not hold it."""
        _synced(workspace, monkeypatch)
        tracker = LosesOneTrace("INC-4822.md")
        gate = Gate(expected=3, meet=3)

        result = _tracked_run(
            workspace, monkeypatch, tracker, GatedModel(gate), "--concurrency", "3"
        )

        assert result.exit_code == 0, result.output
        assert TRACES.findall(result.output) == ["1"]

    def test_concurrency_is_in_the_record_alone(
        self, workspace: Path, tmp_path: Path, monkeypatch
    ):
        """Row 5, a counter-example: three at once against one at a time, the same snapshots."""
        _synced(workspace, monkeypatch)
        assert (
            _tracked_run(
                workspace,
                monkeypatch,
                FakeTracker(),
                GatedModel(Gate(expected=3, meet=3)),
                "--concurrency",
                "3",
            ).exit_code
            == 0
        )
        alone = tmp_path / "alone"
        shutil.copytree(FIXTURES, alone)
        monkeypatch.delenv("DOSSIER_MLFLOW_ENABLED")
        _synced(alone, monkeypatch)
        assert (
            _tracked_run(
                alone,
                monkeypatch,
                FakeTracker(),
                GatedModel(Gate(expected=3)),
                "--concurrency",
                "1",
            ).exit_code
            == 0
        )

        assert _written(workspace) == _written(alone)
        (manifest,) = (workspace / "runs").glob("*/manifest.json")
        assert "concurrency" not in manifest.read_text(encoding="utf-8")


def _written(workspace: Path) -> dict[str, object]:
    """What the run wrote for `extract`: artifacts as bytes, records without `run_id`."""
    (run,) = [path for path in (workspace / "runs").iterdir() if path.is_dir()]
    written: dict[str, object] = {}
    for path in sorted((run / "extract").iterdir()):
        record = json.loads(path.read_bytes())
        if isinstance(record, dict) and "run_id" in record:
            written[path.name] = {k: v for k, v in record.items() if k != "run_id"}
        else:
            written[path.name] = path.read_bytes()
    return written
