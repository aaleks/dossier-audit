"""R8.25 — a document whose default kind nothing converts fails on its own, and
the rest of its source converts.

The automatic case, seen from the command line. The folder source declares no
`convert:`, so every file's kind comes from the default table (R8.10) and its
converter from what is installed (R8.13). `PLAY-4006-indexer-alerts.json` is
`application/json`, and nothing claims `(application/json, markdown)`.

Under R8.5 that one file stopped the source: the exported page and the register
beside it, which two shipped converters read, were not converted either.
Synced from Apache's Jira, `KAFKA-20416`'s `.jsonl` did the same to a whole
project. Nobody asked for the JSON to be read, so nobody misconfigured anything;
it is the JSON that is reported, and the rest is audited.
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
    """A folder of three exports, synced, declaring no `convert:`."""
    inbox = workspace / "inbox" / "exports"
    inbox.mkdir(parents=True)
    for name in (PAGE, REGISTER, ALERTS):
        shutil.copy(EXPORTS / name, inbox / name)

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/exports/\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, name=PIPELINE, sources=[SOURCE])

    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return workspace


class TestAFileNothingConvertsNoLongerStopsItsSource:
    """R8.25 — the automatic choice found nothing, and only that file says so."""

    def test_convert_converts_the_rest_and_names_the_file(self, synced: Path, monkeypatch):
        """Row 1: the one where an exported alert file no longer stops two notes.

        The reason is the refusal R8.5 printed for the whole source, attached to
        the one document it is about: the pair, what is claimed, and where a
        converter comes from.
        """
        result = _cli(synced, monkeypatch, "convert", PIPELINE)

        assert result.exit_code != 0, "a document that was not read is not a clean result"
        assert "3 held · 2 converted · 0 cached" in result.output, result.output
        assert ALERTS in result.output
        assert "('application/json', 'markdown')" in result.output
        assert "(text/html, markdown)" in result.output, "the claimed pairs are listed"
        assert "dossier.converters" in result.output
        assert "have no converter" not in result.output, "no longer the source's refusal"

    def test_a_run_audits_the_two_notes_and_pins_only_their_converters(
        self, synced: Path, monkeypatch
    ):
        """Row 2: the one where the run reads what could be read, and says what could not.

        Two model calls, one per note. The manifest pins the two converters that
        answered, and pins nothing for the JSON: no converter read it, so none is
        part of what the run depended on (R8.9).
        """
        from tests.fakes import FakeModelClient

        import dossier.cli.bootstrap as cli

        model = FakeModelClient(responses=[_answer(PAGE), _answer(REGISTER)])
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0, result.output
        assert ALERTS in result.output
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

    def test_the_plan_after_a_run_promises_what_the_run_did(self, synced: Path, monkeypatch):
        """Row 2 through `--plan`: the one where the plan reads what the run reads.

        After a run, `--plan` says every step is cached. It counted the JSON as a
        document the run would read, so it reported it as `new` and promised a
        step that the next run then served from cache (R4.12).
        """
        from tests.fakes import FakeModelClient

        import dossier.cli.bootstrap as cli

        model = FakeModelClient(responses=[_answer(PAGE), _answer(REGISTER)])
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)
        _cli(synced, monkeypatch, "run", PIPELINE)

        planned = _cli(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert planned.exit_code == 0, planned.output
        assert ALERTS not in planned.output, planned.output
        assert "documents changed" not in planned.output
