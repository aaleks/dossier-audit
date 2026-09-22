"""R11.18 - a `dossier run` records the version of everything it used.

R11.11 gave the eval that scores a run its prompt, schema, converter and
generated-schema versions, read off the manifest. The run that *wrote* that
manifest recorded three params -- its pipeline, its model and its pipeline hash --
so two runs of one pipeline sat side by side in MLflow's run comparison with no
way to see which prompt moved between them. The evals of those two runs answered
it; the runs did not.

The same function over the same plan, at the moment it is resolved rather than at
the moment it is read back. Row 5's claim -- that the run and its eval agree -- is
asserted here as the property it is: what the run recorded is what
`version_params` returns for the plan in the manifest, which is exactly what the
eval logs.
"""

from __future__ import annotations

import json
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

from dossier.domain.resolution import ResolvedPlan
from dossier.domain.tracking import version_params

URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def declared(workspace: Path, monkeypatch) -> Path:
    """The scoring example's four incidents, synced and ready to run."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return workspace


@pytest.fixture
def tracker(declared: Path, monkeypatch) -> FakeTracker:
    """Tracking switched on after the sync, so the runs under test are the runs."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    return recorder


def _manifest_plan(workspace: Path, run_id: str) -> ResolvedPlan:
    """The plan the run wrote, read back the way `dossier eval` reads it."""
    manifest = json.loads(
        (workspace / "runs" / run_id / "manifest.json").read_text(encoding="utf-8")
    )
    return ResolvedPlan.model_validate(manifest["plan"])


class TestARunRecordsWhatProducedIt:
    """R11.18 - the versions of what ran, on the record of the run itself."""

    def test_a_run_records_every_version_its_eval_would(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where the run's own record names its prompts.

        Asserted against `version_params` over the plan in the manifest, which
        is the value `dossier eval` logs (R11.11). Two records of one plan agree
        because they are one function over one set of data, not because two
        computations happened to match (row 5).
        """
        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        run_id = result.output.split("run ", 1)[1].split(" ", 1)[0].strip()
        params = tracker.runs[-1].params
        expected = version_params(_manifest_plan(declared, run_id))
        assert expected, "the plan resolved no steps; this test proves nothing"
        for name, value in expected.items():
            assert params[name] == value, name

    def test_the_versions_sit_beside_the_three_it_already_recorded(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Beside, not instead of. R11.1's three params are what the run page
        has always opened with, and a reader who knows where to look for the
        model should still find it there."""
        assert _cli(declared, monkeypatch, "run", PIPELINE).exit_code == 0

        params = tracker.runs[-1].params
        assert params["pipeline"] == PIPELINE
        assert params["model"] == RoutedModel.model_id
        assert params["converters"]
        assert params["documents"] == str(len(ISSUES))

    def test_an_edited_prompt_moves_exactly_the_param_that_names_it(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one MLflow's run comparison exists for.

        The whole point of the rule: two runs, one edit, and the view that
        compares them names the step. Before this, both records read
        `pipeline_hash` moved and said nothing about which of them did it.
        """
        assert _cli(declared, monkeypatch, "run", PIPELINE).exit_code == 0
        before = dict(tracker.runs[-1].params)

        # The prompt of the one step `write_pipeline` declares. Named rather
        # than globbed: the workspace fixture leaves prompts of its own beside
        # it, and editing one no step reads would move nothing.
        edited = declared / "pipelines" / PIPELINE / "prompts" / "extract.md"
        edited.write_text(
            edited.read_text(encoding="utf-8") + "\nAnswer carefully.\n", encoding="utf-8"
        )
        assert _cli(declared, monkeypatch, "run", PIPELINE).exit_code == 0
        after = dict(tracker.runs[-1].params)

        moved = {name for name in after if before.get(name) != after[name]}
        assert f"prompt/{edited.stem}" in moved
        assert moved <= {f"prompt/{edited.stem}", "pipeline_hash"}, moved

    def test_a_plan_records_no_params_because_it_records_no_run(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example, row 4: the one where nothing was executed.

        `--plan` makes nothing, so it opens no MLflow run at all (R11.1 row 5).
        Params of a plan nobody executed would be a record of work that did not
        happen -- and tracking observes a run, it never precedes one (R0.10).
        """
        result = _cli(declared, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert tracker.runs == []
