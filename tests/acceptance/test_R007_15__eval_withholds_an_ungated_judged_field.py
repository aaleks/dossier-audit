"""R7.15 — `dossier eval` withholds a judged field whose calibration is missing,
short or stale.

R7.5 and R7.6 are pure decisions with their own tests, and until something loads
a calibration and a threshold neither can fire from a command: a field whose
judge has never been measured still prints a percentage, which is the one thing
R7.5 exists to prevent. This rule is what makes both reachable, so the test is an
acceptance test -- what a person running the command sees is the whole claim.

Withheld and *named*, never silently dropped. A missing line reads as a field
nobody verified (R7.3 row 4), which is a different problem wanting different
work.

The overall figure is asserted too, and that is not in the rule's table. Spec 011
says MLflow is "a second place to read it, never a second way of computing it",
and `record_eval` already leaves an ineligible field out of `accuracy/overall`.
A printed overall that still counted the withheld field would make the terminal
and MLflow disagree about the same run -- so it is 14 of 16 here, not 16 of 20.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    FIELDS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.application.eval import judge_prompt_hash
from dossier.domain.hashing import text_hash

JUDGED = "root_cause"
GOLD = "gold/incidents"
BAR = 0.95


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _field_lines(output: str) -> dict[str, str]:
    """Each field's line in the report, by the field name it starts with."""
    return {
        words[0]: line
        for line in output.splitlines()
        if (words := line.split()) and words[0] in FIELDS
    }


def _percentage(line: str) -> str | None:
    found = re.search(r"\d+\.\d%", line)
    return found.group() if found else None


def _rubric(workspace: Path) -> Path:
    return workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """The four documents synced and run, with the bar declared beside the gold set.

    No calibration is written here: each test writes the one it is about, and the
    test that writes none is the "never measured" row.
    """
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output

    (workspace / "gold" / "incidents" / "judge.yaml").write_text(
        f"{JUDGED}: {BAR}\n", encoding="utf-8"
    )
    # Scoring asks no model (R7.10); a call here would be a finding, not a cost.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return workspace


def _calibration(
    workspace: Path,
    *,
    agreement: float,
    judge_model: str = RoutedModel.model_id,
    rubric_hash: str | None = None,
) -> None:
    """What `dossier calibrate` would have left behind (R7.14)."""
    directory = workspace / "gold" / "incidents" / "calibrations"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{JUDGED}.json").write_text(
        json.dumps(
            {
                "judge_model": judge_model,
                "rubric_hash": rubric_hash or text_hash(_rubric(workspace)),
                "prompt_hash": judge_prompt_hash(),
                "agreement": agreement,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _eval(workspace: Path, monkeypatch):
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


class TestEvalWithholdsAnUngatedJudgedField:
    """R7.15 — a judged field is reported only if its judge was measured and cleared."""

    def test_a_judge_below_its_threshold_reports_no_percentage(
        self, audited: Path, monkeypatch
    ):
        """Example 1: the one measured at 0.91 against a declared 0.95.

        No percentage for `root_cause`, and a line saying what it missed by. The
        overall follows the same rule -- 14 of 16, not 16 of 20 -- because the
        terminal and MLflow may not disagree about one run (spec 011).
        """
        _calibration(audited, agreement=0.91)

        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        line = _field_lines(result.output)[JUDGED]
        assert _percentage(line) is None, line
        assert "0.91" in line and "0.95" in line
        assert "87.5%" in result.output, "the overall covers the fields it reported"

    def test_a_stale_calibration_reports_no_percentage(self, audited: Path, monkeypatch):
        """Example 2: the one measured against a judge nobody is using now.

        A calibration measured against another model is not this judge's
        calibration, however good the figure was (R7.6). The line says which half
        moved, because "stale" alone sends someone to guess.
        """
        _calibration(audited, agreement=1.0, judge_model="openai:gpt-5.4-mini")

        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        line = _field_lines(result.output)[JUDGED]
        assert _percentage(line) is None, line
        assert "openai:gpt-5.4-mini" in line

    def test_a_field_never_measured_reports_no_percentage(self, audited: Path, monkeypatch):
        """Example 3: the one with no calibration file at all.

        Never measured is not the same as measured and found wanting, and the
        two want different work: one needs a `dossier calibrate`, the other a
        better judge or an agreed lower bar.
        """
        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        line = _field_lines(result.output)[JUDGED]
        assert _percentage(line) is None, line
        assert "calibrate" in line.lower() or "measured" in line.lower()

    def test_a_judge_exactly_at_its_threshold_is_reported(self, audited: Path, monkeypatch):
        """Example 4: the one measured at precisely the agreed figure.

        The bound is inclusive: a judge that met the bar has met it. The kind of
        thing implemented as `>` by accident, which is why it is a row.
        """
        _calibration(audited, agreement=BAR)

        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        assert _percentage(_field_lines(result.output)[JUDGED]) == "50.0%"

    def test_a_field_scored_by_exact_match_is_unaffected(self, audited: Path, monkeypatch):
        """Counter-example (row 5): `severity` has no judge to be ineligible.

        No judge, no threshold, and no calibration that could be stale (R7.1).
        Asserted with the judged field withheld, so this is the row that fails if
        an ungated judge ever silences the fields beside it.
        """
        _calibration(audited, agreement=0.91)

        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        lines = _field_lines(result.output)
        assert _percentage(lines["severity"]) == "100.0%"
        assert _percentage(lines["loss_amount"]) == "100.0%"
        assert _percentage(lines[JUDGED]) is None
