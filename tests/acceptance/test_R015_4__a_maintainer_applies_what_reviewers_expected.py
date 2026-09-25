"""R15.4 — a reviewer's expected value is a gold candidate, and becomes gold only
when a maintainer applies it.

Observed from the CLI, as a maintainer meets it: `dossier review pull` leaves
`candidates.jsonl` beside `feedback.jsonl`, and `dossier review apply` merges
what is left of it into the gold set under their name. The verdicts reach the
CLI through `build_review_source`, as R15.3's do; the gold set is the fixture
workspace's own, where `INC-4822` is `severity: minor` and `INC-4830` has no
file.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import FakeReviewSource
from tests.pipelines import write_pipeline

from dossier.domain.review import Verdict

PIPELINE = "incident-audit"
GOLD = "gold/incidents"
EXPERIMENT = "dossier-audit/incident-audit/run"
MAJOR = Verdict(
    run="20260806T142203Z-4f1a",
    step="extract",
    document="INC-4822",
    name="severity",
    kind="expectation",
    value="major",
    rationale="payments stopped for an hour",
    reviewer="User",
    at="2026-09-24T09:12:40Z",
    trace="tr-4822",
    assessment="a-0001",
)
CRITICAL = Verdict(
    **{
        **MAJOR.__dict__,
        "value": "critical",
        "trace": "tr-4822b",
        "assessment": "a-0002",
        "reviewer": "j.okafor",
    }
)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _pulled(workspace: Path, monkeypatch, *verdicts: Verdict) -> None:
    import dossier.cli.main as cli

    write_pipeline(workspace)
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "http://localhost:5000")
    source = FakeReviewSource({EXPERIMENT: list(verdicts)})
    monkeypatch.setattr(cli, "build_review_source", lambda settings: source, raising=False)
    result = _cli(workspace, monkeypatch, "review", "pull", PIPELINE)
    assert result.exit_code == 0, result.output


def _severity(workspace: Path) -> dict:
    written = json.loads((workspace / GOLD / "INC-4822.json").read_text(encoding="utf-8"))
    return written["fields"]["severity"]


class TestAMaintainerAppliesWhatReviewersExpected:
    """R15.4 — pull, read, apply, as a maintainer does it."""

    def test_a_pull_leaves_candidates_and_the_gold_set_alone(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: one candidate written, `INC-4822.json` unchanged."""
        before = (workspace / GOLD / "INC-4822.json").read_bytes()

        _pulled(workspace, monkeypatch, MAJOR)

        written = workspace / "review" / PIPELINE / "candidates.jsonl"
        assert len(written.read_text(encoding="utf-8").splitlines()) == 1
        assert (workspace / GOLD / "INC-4822.json").read_bytes() == before

    def test_applying_signs_the_answer_in_the_maintainers_name(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: `severity` becomes `major`, signed by `a.aleks`, `minor` superseded."""
        _pulled(workspace, monkeypatch, MAJOR)

        result = _cli(
            workspace,
            monkeypatch,
            "review",
            "apply",
            PIPELINE,
            "--gold",
            GOLD,
            "--verified-by",
            "a.aleks",
        )

        assert result.exit_code == 0, result.output
        assert "INC-4822  severity  'minor' -> 'major'" in result.output
        assert "1 answer applied to gold/incidents, signed by a.aleks" in result.output
        severity = _severity(workspace)
        assert (severity["value"], severity["verified_by"]) == ("major", "a.aleks")
        assert severity["superseded"] == "minor"

    def test_applying_again_changes_nothing(self, workspace: Path, monkeypatch):
        """Row 4: nothing left to apply, and the file untouched."""
        _pulled(workspace, monkeypatch, MAJOR)
        args = ("review", "apply", PIPELINE, "--gold", GOLD, "--verified-by", "a.aleks")
        assert _cli(workspace, monkeypatch, *args).exit_code == 0
        before = (workspace / GOLD / "INC-4822.json").read_bytes()

        result = _cli(workspace, monkeypatch, *args)

        assert result.exit_code == 0, result.output
        assert "nothing to apply: every candidate is already gold" in result.output
        assert (workspace / GOLD / "INC-4822.json").read_bytes() == before

    def test_a_conflict_is_refused_naming_both(self, workspace: Path, monkeypatch):
        """Row 5, a counter-example: `major` and `critical` for one field."""
        _pulled(workspace, monkeypatch, MAJOR, CRITICAL)
        before = (workspace / GOLD / "INC-4822.json").read_bytes()

        result = _cli(
            workspace,
            monkeypatch,
            "review",
            "apply",
            PIPELINE,
            "--gold",
            GOLD,
            "--verified-by",
            "a.aleks",
        )

        assert result.exit_code == 2
        assert "'major' (User, tr-4822)" in result.output
        assert "'critical' (j.okafor, tr-4822b)" in result.output
        assert (workspace / GOLD / "INC-4822.json").read_bytes() == before

    def test_an_unsigned_apply_is_refused(self, workspace: Path, monkeypatch):
        """Row 9, a counter-example: no `--verified-by`, so no anonymous path into gold."""
        _pulled(workspace, monkeypatch, MAJOR)

        result = _cli(workspace, monkeypatch, "review", "apply", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 2
        assert "--verified-by" in result.output and "R7.7" in result.output
        assert _severity(workspace)["value"] == "minor"
