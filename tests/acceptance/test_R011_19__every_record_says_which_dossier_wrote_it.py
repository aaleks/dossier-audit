"""R11.19 - every record says which `dossier` wrote it.

`dossier_version` was a param on an eval and on none of the other five kinds. A
sync whose counts look wrong, a convert that produced different bytes, a run
whose plan resolved differently: the first question asked of each is which
`dossier` did it, and only the eval could answer.

One param, from the installed distribution's own metadata -- the value R4.9
already writes into every manifest. The eval's is proved by R11.11; this file is
about the five that had none.
"""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeModelClient, FakeTracker
from tests.scoring_example import ISSUES, PIPELINE

PARAM = "dossier_version"
FIELD = "root_cause"


@pytest.fixture
def tracker(two_runs: tuple[Path, str, str], monkeypatch) -> FakeTracker:
    """Tracking switched on after both runs, so each test records its own command."""
    import dossier.cli.bootstrap as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


class TestEveryRecordSaysWhichDossierWroteIt:
    """R11.19 - one param, the same name, on every kind of record."""

    @pytest.mark.parametrize(
        "command",
        [
            pytest.param(("sync",), id="sync"),
            pytest.param(("convert",), id="convert"),
            pytest.param(("run",), id="run"),
        ],
    )
    def test_a_command_records_the_dossier_that_ran_it(
        self,
        two_runs: tuple[Path, str, str],
        monkeypatch,
        tracker: FakeTracker,
        command: tuple[str, ...],
    ):
        """Examples 1 and 2: the same param, under the same name, per kind.

        The run here is served entirely from cache, which is the point worth
        making: a record of a command that asked no model still says which
        `dossier` asked nothing.
        """
        workspace, _, _ = two_runs

        result = _cli(workspace, monkeypatch, *command, PIPELINE)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, command
        assert tracker.runs[0].params[PARAM] == version("dossier")

    def test_a_comparison_records_the_dossier_that_compared(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2 for the kind that reads two runs and makes a third record.

        A comparison's two runs each carry their own version params under `a/`
        and `b/` (R11.11 row 3). This one is not prefixed, because it is not a
        property of either run: it is which `dossier` did the comparing.
        """
        workspace, a, b = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        params = tracker.runs[0].params
        assert params[PARAM] == version("dossier")
        assert f"a/{PARAM}" not in params and f"b/{PARAM}" not in params

    def test_a_calibration_records_the_dossier_that_measured(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2 for the kind whose figures a person later cites.

        A calibration is the most experiment-shaped thing dossier does (spec
        011), and an agreement figure re-measured under a different `dossier`
        is a different measurement -- which the file it writes cannot say and
        the record now can.
        """
        import dossier.cli.bootstrap as cli

        workspace, _, _ = two_runs
        keys = sorted(ISSUES)
        cases = [
            {
                "document": keys[index % len(keys)],
                "answer": f"candidate answer {index}",
                "supported": index < 12,
                "verified_by": "a.aleks",
                "verified_at": "2026-09-15",
            }
            for index in range(20)
        ]
        samples = workspace / "gold" / "incidents" / "samples"
        samples.mkdir(exist_ok=True)
        (samples / f"{FIELD}.jsonl").write_text(
            "\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8"
        )
        judge = FakeModelClient(
            responses=[json.dumps({"supported": case["supported"]}) for case in cases]
        )
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)

        result = _cli(workspace, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].params[PARAM] == version("dossier")

    def test_nothing_is_recorded_when_tracking_is_off(
        self, two_runs: tuple[Path, str, str], monkeypatch
    ):
        """Counter-example, row 4: the one where there is no record to say it on.

        Asserted here rather than left to R10.4 because this rule adds a param
        to five commands, and a param read from installed metadata is exactly
        the kind of value that could be computed before anyone asked whether
        there was anywhere to send it.
        """
        workspace, _, _ = two_runs

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "recorded to MLflow" not in result.output
