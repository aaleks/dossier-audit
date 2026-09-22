"""R10.11 — the label a command is given is rendered into its name and tagged.

A version a person means -- `v2`, `after the prompt rewrite`, `nightly` -- is not
a figure dossier can derive. A count of the runs already on the server would be
one, and it would name the same eval differently on another machine and
differently again after a record was lost (R10.6). So the label is supplied.

In the name so a list reads, and as a tag so a list filters. One value, two
places, one decision -- which is why one test asserts both.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.fakes import FakeTracker, register_connector
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

URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def held(workspace: Path, monkeypatch) -> Path:
    """The four incidents synced, with tracking still off."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


@pytest.fixture
def tracker(monkeypatch) -> FakeTracker:
    """Tracking on, recording to a fake that keeps the name and tags it was handed."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    return recorder


class TestALabelIsInTheNameAndOnTheRecord:
    """R10.11 — the label a command is given is rendered into its name and tagged."""

    def test_a_label_given_on_the_command_line_is_in_the_name_and_on_the_record(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where a person versions two runs of one pipeline by hand.

        The name so the list reads, the tag so the list filters. A label in only
        one of the two is a label that cannot be found by the means a person
        reaches for first.
        """
        result = _cli(held, monkeypatch, "run", PIPELINE, "--label", "v2")

        assert result.exit_code == 0, result.output
        run_id = re.search(r"^run (\S+)", result.output, re.MULTILINE).group(1)
        assert tracker.runs[0].name == f"{run_id} · v2"
        assert tracker.runs[0].tags["dossier.label"] == "v2"

    def test_the_flag_wins_over_the_variable(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where a shell sets a label and the command names another.

        An argument wins over a default everywhere else in this tool, and a
        variable is a default. The alternative -- a variable that could not be
        overridden per command -- would make `DOSSIER_MLFLOW_RUN_LABEL=nightly`
        in a shell silently relabel a run someone made by hand.
        """
        monkeypatch.setenv("DOSSIER_MLFLOW_RUN_LABEL", "nightly")

        result = _cli(held, monkeypatch, "run", PIPELINE, "--label", "v2")

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].tags["dossier.label"] == "v2"
        assert "nightly" not in tracker.runs[0].name

    def test_a_label_set_only_in_the_environment_still_reaches_the_record(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one where a scheduled job labels everything it runs.

        The point of the variable: a nightly job sets it once rather than adding
        a flag to six commands.
        """
        monkeypatch.setenv("DOSSIER_MLFLOW_RUN_LABEL", "nightly")

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].tags["dossier.label"] == "nightly"
        assert tracker.runs[0].name.endswith(" · nightly")

    def test_an_unlabelled_record_carries_no_label_tag_and_no_trailing_separator(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 4): the one where nobody labelled it.

        Absent, not present and empty. Here that is the honest reading: a label
        is supplied or it is not, and an empty `dossier.label` would say someone
        set one to nothing. `dossier.regressed` goes the other way (R11.9 row 3)
        because the command computes it for every comparison, so there absence
        would mean "recorded before the rule existed" instead.
        """
        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "dossier.label" not in tracker.runs[0].tags
        assert not tracker.runs[0].name.endswith(" · ")
