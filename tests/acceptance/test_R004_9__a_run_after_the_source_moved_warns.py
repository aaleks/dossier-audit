"""R4.9 row 4 — a `dossier run` after the source moved resolves against the
current snapshots and says the source has moved since the last run.

The counter-example to replay's frozen pins (rows 1-3): a *new* run reads what
is held now, and the one thing it owes a person is the line saying two runs are
no longer over the same evidence -- before R7.8 refuses to compare them. The
warning is printed before any step runs, so it is read rather than scrolled.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.fakes import register_connector
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


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def source(workspace: Path, monkeypatch) -> IssueTracker:
    """The four incidents, synced and run once; the source can then be changed."""
    import dossier.cli.main as cli

    tracker = IssueTracker(ISSUES)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: tracker)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return tracker


class TestARunAfterTheSourceMovedWarns:
    """R4.9 row 4 — a new run reads what is held now, and says so."""

    def test_a_re_snapshotted_document_is_named_before_any_step_runs(
        self, workspace: Path, monkeypatch, source: IssueTracker
    ):
        """The one where `INC-4821` was re-snapshotted between two runs.

        The warning names the run it is measured against and the document that
        moved, and comes before the run's own lines.
        """
        first = sorted(path.name for path in (workspace / "runs").iterdir())[-1]
        source.issues["INC-4821"] = ISSUES["INC-4821"] + "Addendum: reviewed by finance.\n"
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert (
            lines[0]
            == f"warning: the source has moved since run {first}: INC-4821 re-snapshotted"
        )
        assert re.search(r"^run (\S+)", result.output, re.MULTILINE), "the run still happens"

    def test_a_source_exactly_as_the_last_run_read_it_prints_no_warning(
        self, workspace: Path, monkeypatch, source: IssueTracker
    ):
        """The one where nothing moved: no warning, nothing to scroll past."""
        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "warning" not in result.output
