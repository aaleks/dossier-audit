"""R011.10 — a comparison links the dataset of the gold set it scored.

The same link an eval makes (R11.7), on the other command that scores against a
gold set — so "every run measured against these answers" is one query in MLflow
rather than one per command.

The two runs are built exactly as R11.8's are; this file asserts only the link, so
that a failure here says the link is wrong rather than that the deltas are.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeDatasetRegistry, FakeTracker
from tests.scoring_example import PIPELINE


@pytest.fixture
def recording(two_runs: tuple[Path, str, str], monkeypatch):
    """Tracking on after both runs, with a tracker and a registry that both count."""
    import dossier.cli.bootstrap as cli

    tracker, registry = FakeTracker(), FakeDatasetRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: registry)
    return tracker, registry


def _publish(workspace: Path, monkeypatch) -> None:
    result = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)
    assert result.exit_code == 0, result.output


def _compare(workspace: Path, monkeypatch, a: str, b: str):
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b)


class TestCompareLinksItsDatasetInMLflow:
    """R11.10 — a comparison links the dataset of the gold set it scored."""

    def test_the_comparison_run_carries_the_dataset_it_was_measured_against(
        self,
        two_runs: tuple[Path, str, str],
        monkeypatch,
        recording,
    ):
        """Example 1: the one where the deltas and the answers are one click apart.

        The dataset is an input of the comparison's run, as it is of an eval's —
        so a person filtering MLflow by dataset sees both.
        """
        workspace, a, b = two_runs
        tracker, registry = recording
        _publish(workspace, monkeypatch)

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert run.tags["dossier.kind"] == "compare"
        assert run.inputs == [
            {
                "name": "incidents",
                "dataset_id": registry.find("incidents").dataset_id,
                "digest": registry.find("incidents").digest,
            }
        ]

    def test_a_gold_set_edited_since_publishing_is_linked_and_named_stale(
        self,
        two_runs: tuple[Path, str, str],
        monkeypatch,
        recording,
    ):
        """Example 2: the one where the dataset is behind the answers just scored.

        Named rather than obeyed, as on an eval (R11.7 row 2): the deltas came
        from the files.
        """
        workspace, a, b = two_runs
        tracker, _ = recording
        _publish(workspace, monkeypatch)
        path = workspace / "gold" / "incidents" / "INC-4821.json"
        edited = json.loads(path.read_text(encoding="utf-8"))
        edited["fields"]["severity"] = {"value": "minor"}
        path.write_text(json.dumps(edited, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert tracker.runs[-1].tags["dossier.dataset_stale"] == "true"

    def test_an_unpublished_gold_set_records_the_deltas_and_links_nothing(
        self,
        two_runs: tuple[Path, str, str],
        monkeypatch,
        recording,
    ):
        """Counter-example (row 3): the one where nobody published this gold set.

        Not an error. The comparison records everything R11.8 says it records and
        simply has nothing to link (R11.7 row 3).
        """
        workspace, a, b = two_runs
        tracker, _ = recording

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert run.inputs == []
        assert run.metrics["delta/affected_systems"] == -25.0, "the deltas are still recorded"
