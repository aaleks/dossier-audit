"""R7.29 — `dossier calibrate` prints, writes and records the same lower bound,
kappa and counts. The CLI half.

The unit test beside this one proves what each place is given. This one proves
the command gives it: the line a person reads under the agreement, the file
committed beside the gold set, and the MLflow run -- the three places R11.5
already holds to one agreement figure, now holding what that figure hides.

The judge is a `FakeModelClient` and the tracker a `FakeTracker`, handed to the
CLI through the seams every other acceptance test uses, so no model and no
server is reached (R0.1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

FIELD = "root_cause"
GOLD = "gold/incidents"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
URI = "http://localhost:5000"

# Twelve supported and eight unsupported, as the sample R7.11 measured is.
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


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def calibratable(workspace: Path, monkeypatch) -> Path:
    """A synced workspace whose gold set carries a twenty-case sample."""
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
    (gold / "samples" / f"{FIELD}.jsonl").write_text(
        "\n".join(json.dumps(case) for case in _cases()) + "\n", encoding="utf-8"
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


class TestCalibrateReportsWhatItsAgreementHides:
    """R7.29 — the terminal, the file and the run, holding the same figures."""

    def test_the_terminal_the_file_and_the_run_hold_the_same_figures(
        self, calibratable: Path, monkeypatch
    ):
        """Rows 1 and 2: the one where the three places agree.

        Twenty of twenty, so the line reads as R7.29 row 1 does: 100.0% above,
        and 83.9% below it, the gap between what the sample showed and what it
        can support.
        """
        import dossier.cli.bootstrap as cli

        tracker = FakeTracker()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
        replies = [json.dumps({"supported": case["supported"]}) for case in _cases()]
        monkeypatch.setattr(
            cli, "build_model_client", lambda model_id: FakeModelClient(responses=replies)
        )

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        above = lines.index(f"{FIELD}         100.0% agreement over 20 cases · {MODEL}")
        assert lines[above + 1] == (
            " " * 19
            + "lower bound 83.9% · kappa 1.00 · supported 12 of 12 · unsupported 8 of 8"
        )

        written = json.loads(
            (calibratable / "gold" / "incidents" / "calibrations" / f"{FIELD}.json").read_text(
                encoding="utf-8"
            )
        )
        assert written["lower_bound"] == pytest.approx(0.838874842, abs=1e-9)
        assert written["kappa"] == 1.0
        assert written["supported"] == {"agreed": 12, "cases": 12}
        assert written["unsupported"] == {"agreed": 8, "cases": 8}

        (run,) = tracker.runs
        assert run.metrics == {
            f"judge/{FIELD}/agreement": 100.0,
            f"judge/{FIELD}/cases": 20,
            f"judge/{FIELD}/lower_bound": 83.9,
            f"judge/{FIELD}/kappa": 1.0,
            f"judge/{FIELD}/supported": 100.0,
            f"judge/{FIELD}/unsupported": 100.0,
        }
        assert lines[above + 1].strip() in run.tags["mlflow.note.content"].splitlines()

    def test_a_figure_that_is_not_measurable_is_said_in_words(
        self, calibratable: Path, monkeypatch
    ):
        """Row 4: the one where the reviewer marked every case supported.

        Nothing to measure kappa on and nothing to count in the unsupported
        half: the terminal says so, and the file holds `null` and a zero count
        rather than a figure a reader would quote.
        """
        import dossier.cli.bootstrap as cli

        every = [{**case, "supported": True} for case in _cases()]
        (calibratable / "gold" / "incidents" / "samples" / f"{FIELD}.jsonl").write_text(
            "\n".join(json.dumps(case) for case in every) + "\n", encoding="utf-8"
        )
        replies = [json.dumps({"supported": True})] * len(every)
        monkeypatch.setattr(
            cli, "build_model_client", lambda model_id: FakeModelClient(responses=replies)
        )

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert (
            " " * 19 + "lower bound 83.9% · kappa not measurable · supported 20 of 20 · "
            "no unsupported case"
        ) in result.output.splitlines()
        written = json.loads(
            (calibratable / "gold" / "incidents" / "calibrations" / f"{FIELD}.json").read_text(
                encoding="utf-8"
            )
        )
        assert written["kappa"] is None
        assert written["unsupported"] == {"agreed": 0, "cases": 0}
