"""R8.24 — a pair nothing claims stops the run only when the source declared its
kind -- and it stops it before anything converts, in every source.

Rows 1 and 3 say the run stops before anything converts and that the failure is
total. That held within one source and not across two: each command converted
source by source, so a refusal in the second came after the first had written
its artifacts, and nothing said so. Playground exercise 10 found it, making a
screenshots source ask for `markdown` beside a source that had converted ten
documents.

Two folder sources here. `incidents-manual` declares nothing and holds three
notes every installation reads. `incidents-exports` declares
`convert: [markdown]` and holds `PLAY-4006-indexer-alerts.json`, a pair nothing
claims. It is listed second, so it is the one a source-by-source loop reaches
last.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
ALERTS = "PLAY-4006-indexer-alerts.json"
EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "exports"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _artifacts(workspace: Path) -> list[Path]:
    cache = workspace / ".dossier" / "cache" / "convert"
    return [path for path in cache.rglob("*") if path.is_file()] if cache.exists() else []


@pytest.fixture
def two_sources(workspace: Path, monkeypatch) -> Path:
    inbox = workspace / "inbox" / "exports"
    inbox.mkdir(parents=True)
    shutil.copy(EXPORTS / ALERTS, inbox / ALERTS)
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: incidents-manual\n    type: folder\n    path: inbox/incidents/\n"
        "  - id: incidents-exports\n    type: folder\n    path: inbox/exports/\n"
        "    convert: [markdown]\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, sources=["incidents-manual", "incidents-exports"])
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return workspace


class TestARefusalInOneSourceConvertsNothingInAnother:
    """R8.24 rows 1 and 3 — before anything converts means in any source."""

    def test_convert_writes_no_artifact_for_the_source_it_could_read(
        self, two_sources: Path, monkeypatch
    ):
        """Row 3: the one where the notes are not converted either.

        The refusal names the JSON, and the three notes of the first source are
        not in the cache: nothing about this run is well-defined, so nothing of
        it is kept.
        """
        result = _cli(two_sources, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 2, result.output
        assert ALERTS in result.output
        assert "('application/json', 'markdown')" in result.output
        assert _artifacts(two_sources) == []

    def test_run_asks_no_model_and_converts_nothing(self, two_sources: Path, monkeypatch):
        """Row 3 through `dossier run`: no artifact, and no stage runs."""
        from tests.fakes import NoModelClient

        import dossier.cli.bootstrap as cli

        monkeypatch.setattr(
            cli, "build_model_client", lambda model_id: NoModelClient(), raising=False
        )

        result = _cli(two_sources, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert ALERTS in result.output
        assert _artifacts(two_sources) == []
