"""R15.3 — `dossier review pull` writes every valid human verdict on a pipeline's
runs, and reports them by step and name.

Observed from the CLI, because it is a maintainer's command: tracking switched
on the way a person switches it on (R10.1), the verdicts handed to the CLI
through `build_review_source`, the seam `build_dataset_registry` is for spec
012, and what they read is the file under `review/` and the lines printed.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeReviewSource
from tests.pipelines import write_pipeline

from dossier.domain.review import Verdict

PIPELINE = "incident-audit"
URI = "http://localhost:5000"
EXPERIMENT = "dossier-audit/incident-audit/run"
REASON = "payments stopped for an hour: major, not minor"
NO = Verdict(
    run="20260806T142203Z-4f1a",
    step="extract",
    document="INC-4822",
    name="severity",
    kind="feedback",
    value=False,
    rationale=REASON,
    reviewer="User",
    at="2026-09-24T09:12:40Z",
    trace="tr-4822",
    assessment="a-0001",
)
YES = Verdict(
    run="20260806T142203Z-4f1a",
    step="verify",
    document="INC-4821",
    name="overall",
    kind="feedback",
    value=True,
    rationale=None,
    reviewer="s.brunner",
    at="2026-09-24T09:20:02Z",
    trace="tr-4821",
    assessment="a-0002",
)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _pull(workspace: Path, monkeypatch, verdicts: list[Verdict] | None, *, tracked=True):
    import dossier.cli.review as review_cli

    write_pipeline(workspace)
    if tracked:
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    source = FakeReviewSource({EXPERIMENT: verdicts or []})
    monkeypatch.setattr(
        review_cli, "build_review_source", lambda settings: source, raising=False
    )
    return _cli(workspace, monkeypatch, "review", "pull", PIPELINE)


class TestAReviewersVerdictsComeBack:
    """R15.3 — the command a maintainer runs, and what it leaves behind."""

    def test_a_pull_writes_the_verdicts_and_reports_them(self, workspace: Path, monkeypatch):
        """Rows 1 and 5: a no on `extract`'s `severity`, a yes on `verify`'s `overall`."""
        result = _pull(workspace, monkeypatch, [NO, YES])

        assert result.exit_code == 0, result.output
        written = workspace / "review" / PIPELINE / "feedback.jsonl"
        assert len(written.read_text(encoding="utf-8").splitlines()) == 2
        assert "extract  severity  0 yes · 1 no" in result.output
        assert f"INC-4822  User: {REASON}" in result.output
        assert "verify  overall  1 yes · 0 no" in result.output
        assert "review/incident-audit/feedback.jsonl" in result.output

    def test_a_second_pull_with_nothing_new_changes_nothing(self, workspace: Path, monkeypatch):
        """Row 4: the same bytes, so `git diff` is empty."""
        assert _pull(workspace, monkeypatch, [NO, YES]).exit_code == 0
        written = workspace / "review" / PIPELINE / "feedback.jsonl"
        before = written.read_bytes()

        assert _pull(workspace, monkeypatch, [YES, NO]).exit_code == 0

        assert written.read_bytes() == before

    def test_tracking_off_is_refused_before_any_work(self, workspace: Path, monkeypatch):
        """Row 6, a counter-example: its whole input is the server."""
        result = _pull(workspace, monkeypatch, [NO], tracked=False)

        assert result.exit_code == 2
        assert "DOSSIER_MLFLOW_ENABLED" in result.output
        assert not (workspace / "review").exists()

    def test_no_verdict_says_so_and_writes_nothing(self, workspace: Path, monkeypatch):
        """Row 7, a counter-example: nobody has reviewed anything yet."""
        result = _pull(workspace, monkeypatch, [])

        assert result.exit_code == 0, result.output
        assert "no reviewer verdicts on incident-audit's runs" in result.output
        assert not (workspace / "review").exists()
