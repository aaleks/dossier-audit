"""R8.27 — a media type `convert:` maps to `[]` is not read, and its documents
are reported as left out, not failed.

R8.25's cost, seen from the command line and then paid off. A folder holds an
exported page, a register and `PLAY-4006-indexer-alerts.json`. Declaring no
`convert:`, the JSON fails on its own and every command exits non-zero, run
after run, over a file nobody wants read (R8.25's acceptance test).

`convert: {application/json: []}` says so in `sources.yaml`. The JSON is still
synced and held, and it is counted -- `1 left out` -- so the choice shows in
every command's output. Nothing fails, so the exit is 0.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "export-audit"
SOURCE = "incidents-exports"

EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "exports"
PAGE = "PLAY-4001-payment-retries.html"
REGISTER = "PLAY-4004-incident-register.csv"
ALERTS = "PLAY-4006-indexer-alerts.json"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _answer(document: str) -> str:
    return json.dumps({"document": document, "fields": []})


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """A folder of three exports, synced, leaving JSON out on purpose."""
    inbox = workspace / "inbox" / "exports"
    inbox.mkdir(parents=True)
    for name in (PAGE, REGISTER, ALERTS):
        shutil.copy(EXPORTS / name, inbox / name)

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/exports/\n"
        "    convert:\n      application/json: []\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, name=PIPELINE, sources=[SOURCE])

    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    assert "3 new" in result.output, "the JSON is synced and held like the others"
    return workspace


@pytest.mark.outer_loop
class TestAJsonExportLeftOutOnPurpose:
    """R8.27 — a file a source said it does not read is counted, not failed."""

    def test_convert_counts_the_json_as_left_out_and_exits_zero(
        self, synced: Path, monkeypatch
    ):
        """Row 1: the one where the JSON is left out, and says so."""
        result = _cli(synced, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "3 held · 2 converted · 0 cached · 1 left out" in result.output
        assert "failed" not in result.output

    def test_a_run_reads_the_two_notes_and_pins_nothing_for_the_json(
        self, synced: Path, monkeypatch
    ):
        """Row 2: the one where the run is clean, over what the source reads."""
        from tests.fakes import FakeModelClient

        import dossier.cli.main as cli

        model = FakeModelClient(responses=[_answer(PAGE), _answer(REGISTER)])
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert model.call_count == 2
        manifest = json.loads(
            next((synced / "runs").rglob("manifest.json")).read_text(encoding="utf-8")
        )
        assert {document["key"] for document in manifest["plan"]["documents"]} == {
            PAGE,
            REGISTER,
        }
        assert sorted(c["id"] for c in manifest["plan"]["converters"]) == [
            "html-markdown",
            "text-csv",
        ]
