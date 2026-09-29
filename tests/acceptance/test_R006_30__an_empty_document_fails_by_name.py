"""R6.30 — `dossier run` over an empty document fails it by name, asks about the
others, and replays.

The acceptance rule for R6.28 and R6.29, observed through the CLI as a person
runs it: the folder source `incidents-manual` holding a real incident,
`INC-4821.md`, and `handover-note.md`, zero bytes -- what an export that wrote
nothing leaves behind (`_fixtures.md`). Before the guard, the empty note was
asked about as `<document key="handover-note.md"></document>` and the answer
cached, a call about nothing.

The model is a `FakeModelClient` that **counts calls**. A replay is asked of a
`NoModelClient`: a model call there would be a finding (R4.7).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
SOURCE = "incidents-manual"
INCIDENT = "INC-4821.md"
EMPTY = "handover-note.md"
URI = "http://localhost:5000"


def _answer(document: str) -> str:
    return json.dumps({"document": document, "fields": [abstains(f) for f in FIELDS]})


def _run(workspace: Path, monkeypatch, *, note: str = "", tracker=None):
    """Sync the folder source and run `extract` over it; the result and the model."""
    from tests.fakes import FakeModelClient

    import dossier.cli.bootstrap as cli

    inbox = workspace / "inbox" / "manual"
    inbox.mkdir(parents=True)
    (inbox / INCIDENT).write_text(
        "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n", encoding="utf-8"
    )
    (inbox / EMPTY).write_text(note, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/manual/\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, name=PIPELINE, sources=[SOURCE])

    # Enough answers for both documents, so a call about the empty note is
    # counted rather than refused by the fake.
    model = FakeModelClient(responses=[_answer(INCIDENT), _answer(EMPTY)])
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)
    if tracker is not None:
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return _cli(workspace, monkeypatch, "run", PIPELINE), model


class TestAnEmptyDocumentFailsByName:
    """R6.30 — an empty document fails by name, the others are asked, and it replays."""

    def test_the_empty_note_fails_and_the_incident_is_asked(self, workspace: Path, monkeypatch):
        """Row 1 — the one where one call is made, for the incident alone."""
        result, model = _run(workspace, monkeypatch)

        assert result.exit_code == 1, result.output
        assert model.call_count == 1, "the empty note was asked about"
        assert "  extract: 2 document(s) · 0 from cache · 1 failed" in result.output, (
            result.output
        )
        assert f"    extract failed on {EMPTY}" in result.stderr.splitlines(), result.stderr

    def test_the_trace_says_which_input_was_empty(self, workspace: Path, monkeypatch):
        """Row 2 — the one where MLflow shows why, with no model span."""
        from tests.fakes import FakeTracker

        tracker = FakeTracker()
        _run(workspace, monkeypatch, tracker=tracker)

        (trace,) = [trace for trace in tracker.traces if trace.name == f"extract · {EMPTY}"]
        assert trace.status == "ERROR"
        assert "every input it reads is empty: documents" in (trace.error or ""), trace.error
        assert [span for span in trace.spans if span["kind"] == "llm"] == []

    def test_the_run_replays(self, workspace: Path, monkeypatch):
        """Row 3 — the one reproduced without asking for what was never written."""
        from tests.fakes import NoModelClient

        import dossier.cli.bootstrap as cli

        _run(workspace, monkeypatch)
        (run_id,) = sorted(path.name for path in (workspace / "runs").iterdir())
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _cli(workspace, monkeypatch, "run", "--replay", f"runs/{run_id}")

        assert "1 artifact(s) reproduced" in result.output, result.output
        assert "cannot be reproduced" not in result.output, result.output

    def test_a_note_with_a_line_in_it_is_asked(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one where the note holds something."""
        result, model = _run(workspace, monkeypatch, note="Handed over to the night shift.\n")

        assert result.exit_code == 0, result.output
        assert model.call_count == 2
        assert "  extract: 2 document(s) · 0 from cache · 0 failed" in result.output, (
            result.output
        )
