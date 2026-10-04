"""R21.25 — a masked run records how many values of each type it masked, and never
a value.

A reviewer reading a run in MLflow cannot tell that masking happened, or how
much of it: the traces hold placeholders, and nothing says how many. A masked
run now records `masked/<TYPE>` metrics on its MLflow run -- counts, from the
masked views' records, so a run whose views were all served from the cache
says what the run that masked them said.

`PLAY-6001` names two people and holds one IBAN.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.fakes import CANARIES, FakeMasker, FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, IssueTracker, abstains

PLAY_6001 = (
    "# PLAY-6001\n\nHans Muster reported that the export never ran.\n"
    "Erika Mustermann holds account CH93 0076 2011 6238 5295 7.\n"
)
MASKING = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON, IBAN_CODE]\n"
)
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        (key,) = SHOWN.findall(prompt)
        return json.dumps({"document": key, "fields": [abstains(f) for f in FIELDS]})


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _runs(workspace: Path, monkeypatch, *, masked: bool = True, times: int = 1) -> FakeTracker:
    """`PLAY-6001` synced and run `times` times, recorded to a fake tracker."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: incidents-jira\n    type: issue-tracker\n", encoding="utf-8"
    )
    path = write_pipeline(workspace, sources=["incidents-jira"])
    if masked:
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        (path.parent / "masking").mkdir()
        (path.parent / "masking" / "cid.yaml").write_text(MASKING, encoding="utf-8")
    register_connector(
        monkeypatch,
        "issue-tracker",
        lambda config, *, workspace: IssueTracker({"PLAY-6001": PLAY_6001}),
    )
    tracker = FakeTracker()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
    monkeypatch.setattr(cli, "build_masker", lambda declaration: FakeMasker(), raising=False)
    assert _cli(workspace, monkeypatch, "sync", "incident-audit").exit_code == 0
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "http://localhost:5000")
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    for _ in range(times):
        result = _cli(workspace, monkeypatch, "run", "incident-audit")
        assert result.exit_code == 0, result.output
    return tracker


def _masked_metrics(run) -> dict[str, float]:
    return {name: value for name, value in run.metrics.items() if name.startswith("masked/")}


class TestAMaskedRunRecordsWhatItMasked:
    """R21.25 — `masked/<TYPE>` counts on the run, and no value anywhere on it."""

    def test_the_run_records_how_many_values_of_each_type_it_masked(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where two people and an IBAN were masked."""
        tracker = _runs(workspace, monkeypatch)

        (run,) = tracker.runs

        assert _masked_metrics(run) == {"masked/IBAN_CODE": 1, "masked/PERSON": 2}

    def test_a_run_served_from_the_cache_records_the_same_counts(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where every view comes from the cache."""
        tracker = _runs(workspace, monkeypatch, times=2)

        first, second = tracker.runs

        assert _masked_metrics(second) == _masked_metrics(first)

    def test_no_param_metric_or_tag_holds_a_value(self, workspace: Path, monkeypatch):
        """Row 3: the one where the counts are all that is said."""
        tracker = _runs(workspace, monkeypatch)

        (run,) = tracker.runs
        said = repr(run.params) + repr(run.metrics) + repr(run.tags)

        assert [value for value in CANARIES if value in said] == []

    def test_an_unmasked_run_records_no_masked_metric(self, workspace: Path, monkeypatch):
        """Row 4, a counter-example: the one where nothing is declared."""
        tracker = _runs(workspace, monkeypatch, masked=False)

        (run,) = tracker.runs

        assert _masked_metrics(run) == {}
