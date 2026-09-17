"""R7.14 — `dossier calibrate` measures a judge and writes the calibration beside
the gold set. The CLI half.

The unit test beside this one proves what a measurement *writes*. This one proves
a command *makes* one -- which is the rule's Given, and which is the half that
went missing in R11.3 and R11.4: a rule fully proved one layer below the thing it
promises, with `record_eval` sitting uncalled for weeks and every check green.

The judge is a `FakeModelClient` handed to the CLI through the same seam every
other acceptance test uses, so no model is reached (R0.1). The documents come
from an issue-tracker source rather than the fixture folder, because a folder
keys a document by its file name -- `INC-4821.md` -- while a gold set and its
sample are keyed by the document itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, register_connector
from tests.pipelines import RUBRIC, write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

from dossier.application.eval import judge_prompt_hash
from dossier.domain.hashing import text_hash

FIELD = "root_cause"
GOLD = "gold/incidents"
MODEL = "anthropic:claude-sonnet-4-5-20250929"

# Twenty cases over the four documents the source holds, split twelve supported
# to eight as the sample R7.11 measured is. A document appearing in several cases
# is the ordinary shape: one candidate answer per case, not one per document.
VERDICTS = [True] * 12 + [False] * 8


def _cases() -> list[dict]:
    keys = sorted(ISSUES)
    return [
        {
            "document": keys[index % len(keys)],
            "answer": f"candidate answer {index}",
            "supported": supported,
            "verified_by": "a.aleks",
            "verified_at": "2026-09-15",
        }
        for index, supported in enumerate(VERDICTS)
    ]


def _replies(cases: list[dict], *, disagree_at: int | None = None) -> list[str]:
    """What the judge answers, case by case: the reviewer's verdict, or its opposite."""
    return [
        json.dumps(
            {"supported": case["supported"] if index != disagree_at else not case["supported"]}
        )
        for index, case in enumerate(cases)
    ]


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def calibratable(workspace: Path, monkeypatch) -> Path:
    """A synced workspace whose gold set carries a bar and a twenty-case sample."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    path = write_pipeline(workspace, sources=[SOURCE_ID])
    path.write_text(path.read_text(encoding="utf-8") + f"gold: {GOLD}/\n", encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )

    gold = workspace / "gold" / "incidents"
    (gold / "samples").mkdir(parents=True)
    # The bar a person agreed, which a measurement may never move (R7.13).
    (gold / "judge.yaml").write_text(f"{FIELD}: 0.95\n", encoding="utf-8")
    (gold / "samples" / f"{FIELD}.jsonl").write_text(
        "\n".join(json.dumps(case) for case in _cases()) + "\n", encoding="utf-8"
    )

    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


def _calibration(workspace: Path) -> dict:
    path = workspace / "gold" / "incidents" / "calibrations" / f"{FIELD}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestCalibrateWritesTheCalibrationFile:
    """R7.14 — the command measures the judge and leaves the figure behind."""

    def test_calibrate_writes_what_it_measured_beside_the_gold_set(
        self, calibratable: Path, monkeypatch
    ):
        """Example 1: the one over a twenty-case sample, with one disagreement.

        Nineteen of twenty, so 0.95, carrying the judge that produced it and a
        hash of the rubric it was measured against -- the two things R7.6 needs
        to notice later that this figure belongs to a judge nobody is using.
        """
        import dossier.cli.main as cli

        cases = _cases()
        judge = FakeModelClient(responses=_replies(cases, disagree_at=7))
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert judge.call_count == 20, "one judge call per case"
        rubric = calibratable / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"
        assert rubric.read_text(encoding="utf-8") == RUBRIC
        assert _calibration(calibratable) == {
            "judge_model": MODEL,
            "rubric_hash": text_hash(rubric),
            "prompt_hash": judge_prompt_hash(),
            "agreement": 0.95,
            "sample_size": 20,
        }

    def test_a_second_run_replaces_the_figure(self, calibratable: Path, monkeypatch):
        """Example 2: the one measured again after something moved.

        The file records what is true now. Two answers to "what did this judge
        score" is the state R7.6 exists to prevent anyone reaching.
        """
        import dossier.cli.main as cli

        cases = _cases()
        monkeypatch.setattr(
            cli,
            "build_model_client",
            lambda model_id: FakeModelClient(responses=_replies(cases, disagree_at=7)),
        )
        first = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)
        assert first.exit_code == 0, first.output
        assert _calibration(calibratable)["agreement"] == 0.95

        monkeypatch.setattr(
            cli,
            "build_model_client",
            lambda model_id: FakeModelClient(responses=_replies(cases)),
        )
        second = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert second.exit_code == 0, second.output
        assert _calibration(calibratable)["agreement"] == 1.0

    def test_a_sample_below_the_minimum_refuses_and_writes_nothing(
        self, calibratable: Path, monkeypatch
    ):
        """Example 3: the one whose sample is nineteen cases long.

        Refused, naming the count, and no file left behind -- a file would read
        back as a calibration, and "refused" would have produced one anyway
        (R7.11 row 3).
        """
        import dossier.cli.main as cli

        short = _cases()[:-1]
        (calibratable / "gold" / "incidents" / "samples" / f"{FIELD}.jsonl").write_text(
            "\n".join(json.dumps(case) for case in short) + "\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            cli,
            "build_model_client",
            lambda model_id: FakeModelClient(responses=_replies(short)),
        )

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code != 0
        assert "19" in result.output
        assert not (calibratable / "gold" / "incidents" / "calibrations").exists()
