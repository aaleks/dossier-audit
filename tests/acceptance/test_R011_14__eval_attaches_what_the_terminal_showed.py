"""R11.14 — an eval and a comparison attach the detail they printed.

The unit test beside this one proves what the artifacts hold. This one proves
the commands attach them, and that what is in them is what was on screen: the
per-document lines are read out of the command's own output and matched against
the entries.

Before this, a run's record carried `manifest.json` and a sync's carried
`changes.json`, and an eval's carried nothing at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeTracker, NoModelClient
from tests.scoring_example import PIPELINE

SCORES = "scores.json"
DELTAS = "deltas.md"


@pytest.fixture
def tracker(monkeypatch) -> FakeTracker:
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return recorder


class TestEvalAttachesWhatTheTerminalShowed:
    """R11.14 — an eval and a comparison attach the detail they printed."""

    def test_an_eval_attaches_an_entry_for_every_verdict_it_reached(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where the terminal has scrolled away.

        Four documents by five fields, minus whatever went to a judge that may
        not be quoted. The count is compared against the report's own field and
        document counts rather than against a literal.
        """
        workspace, _, _ = two_runs

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        documents, fields = re.search(r"(\d+) documents · (\d+) fields", result.output).groups()
        attached = json.loads(tracker.runs[0].artifacts[SCORES])
        assert len(attached["scores"]) == int(documents) * int(fields)

    def test_the_entries_carry_the_reasons_the_report_printed(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where the artifact and the terminal cannot disagree.

        Each miss the report printed under a field is looked up in the artifact
        by its document, and its detail must be the line's own words.
        """
        workspace, _, _ = two_runs

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        printed = re.findall(r"^    (\S+)\s{2,}(.+)$", result.output, re.MULTILINE)
        assert printed, result.output
        details = {
            (entry["document"], entry["detail"])
            for entry in json.loads(tracker.runs[0].artifacts[SCORES])["scores"]
            if entry["detail"]
        }
        for document, detail in printed:
            assert (document, detail.strip()) in details, (document, detail)

    def test_a_comparison_attaches_the_table_it_printed(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one read a month after the terminal closed."""
        workspace, a, b = two_runs

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b
        )

        assert result.exit_code == 0, result.output
        table = tracker.runs[0].artifacts[DELTAS].decode("utf-8")
        assert f"compare {a} -> {b}" in table
        assert "affected_systems" in table
        assert "-25.0" in table, table

    def test_attaching_an_artifact_writes_nothing_to_the_workspace(
        self, two_runs: tuple[Path, str, str], monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 6): the one where the record is not an output.

        `runs/` and `.dossier/` are listed before and after. The artifact is
        built from what was printed and written nowhere else (R10.4, R0.11).
        """
        workspace, _, _ = two_runs
        before = sorted(p.relative_to(workspace) for p in workspace.rglob("*") if p.is_file())

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].artifacts[SCORES], "something was attached"
        after = sorted(p.relative_to(workspace) for p in workspace.rglob("*") if p.is_file())
        assert after == before
