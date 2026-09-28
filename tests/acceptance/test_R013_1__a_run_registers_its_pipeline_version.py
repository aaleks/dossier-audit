"""R13.1 - a pipeline version is one ready logged model, found or created.

The Models tab beside every dossier experiment has always been empty. This is
the rule that fills it: one row per pipeline version, found by the pair
(pipeline name, version hash) so that running the same pipeline twice adds a
measurement rather than a row.

Found, not assumed. A live spike against MLflow 3.15.1 established that creating
a logged model by name alone makes a new object every single time -- so a
registry that did not look first would leave one model per run, and comparing
two of them would compare nothing with nothing. The same spike established that
`name = '<pipeline>' AND params.version_hash = '<hash>'` returns exactly one
where either half alone returns two, which is why rows 4 and 5 below are the
counter-examples that matter.

The registry is a `FakeVersionRegistry`, handed to the CLI through the same seam
`build_dataset_registry` uses. It returns an id, which is the whole reason it is
a port of its own rather than a method on `Tracker` (R0.10).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeTracker, FakeVersionRegistry, register_connector
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
OTHER = "postmortem-review"


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
def registry(declared: Path, monkeypatch) -> FakeVersionRegistry:
    """Tracking on, at a fake tracker and a fake registry, after the sync."""
    import dossier.cli.bootstrap as cli

    versions = FakeVersionRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: FakeTracker(), raising=False)
    monkeypatch.setattr(cli, "build_version_registry", lambda settings: versions, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    return versions


def _edit_prompt(workspace: Path, pipeline: str = PIPELINE) -> None:
    """Move the version the way a person does: change a prompt.

    Note what this does *not* move: `pipeline_hash`, which is the hash of
    `pipeline.yaml` and is untouched by editing a file it merely names.
    """
    prompt = workspace / "pipelines" / pipeline / "prompts" / "extract.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nBe precise.\n", encoding="utf-8")


class TestARunRegistersItsPipelineVersion:
    """R13.1 - one ready logged model per (pipeline, version hash)."""

    def test_a_run_registers_the_version_it_produced(
        self, declared: Path, monkeypatch, registry: FakeVersionRegistry
    ):
        """Example 1: the one where the Models tab stops being empty.

        Named after the pipeline, because that is what a person compares
        versions *of*, and carrying `version_params` so the row says which
        prompts and schemas this version is (R11.18).
        """
        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert len(registry.versions) == 1, registry.registrations
        version = registry.versions[0]
        assert version.name == PIPELINE
        assert version.experiment == f"dossier-audit/{PIPELINE}/run"
        assert version.params["pipeline_hash"]
        assert version.params["prompt/extract"]
        assert version.params["model"] == RoutedModel.model_id
        assert version.ready, "a version left pending is an unfinished record"

    def test_running_the_same_pipeline_twice_is_one_version(
        self, declared: Path, monkeypatch, registry: FakeVersionRegistry
    ):
        """Example 2: the one the live spike made necessary.

        MLflow creates a new logged model every time it is asked by name, so
        this is the assertion that catches a registry that does not look first.
        Two runs, two registration calls, one version.
        """
        assert _cli(declared, monkeypatch, "run", PIPELINE).exit_code == 0
        assert _cli(declared, monkeypatch, "run", PIPELINE).exit_code == 0

        assert len(registry.registrations) == 2, "both runs asked"
        assert len(registry.versions) == 1, "and both got the same version"

    def test_an_edited_prompt_is_a_second_version(
        self, declared: Path, monkeypatch, registry: FakeVersionRegistry
    ):
        """Example 3: two rows in the Models tab, which is the comparison.

        Editing a prompt moves the version hash and leaves `pipeline_hash`
        exactly where it was. Before and after sit side by side, which they
        would not under the identity this rule was first written with.
        """
        assert _cli(declared, monkeypatch, "run", PIPELINE).exit_code == 0
        _edit_prompt(declared)
        assert _cli(declared, monkeypatch, "run", PIPELINE).exit_code == 0

        assert len(registry.versions) == 2
        # On the version hash, not `pipeline_hash`. The latter is
        # `text_hash(pipeline.yaml)` and does not move when a prompt does, which
        # is what this row caught: keyed on it, an edited prompt shared a row
        # with the prompt it replaced and there was nothing to compare.
        versions = {version.params["version_hash"] for version in registry.versions}
        assert len(versions) == 2, "an edited prompt is a second version"
        assert len({v.params["pipeline_hash"] for v in registry.versions}) == 1
        assert {version.name for version in registry.versions} == {PIPELINE}

    def test_two_pipelines_at_one_hash_are_two_versions(
        self, declared: Path, monkeypatch, registry: FakeVersionRegistry
    ):
        """Counter-example, row 4: the one where the hash alone would lie.

        `postmortem-review` is written byte-identically to `incident-audit`, so
        both resolve to the same version hash. A registry matching on the digest
        alone would hand one pipeline's accuracy to the other -- which the live
        spike showed is possible, since a params filter alone returned both.
        """
        assert _cli(declared, monkeypatch, "run", PIPELINE).exit_code == 0
        write_pipeline(declared, name=OTHER, sources=[SOURCE_ID])

        assert _cli(declared, monkeypatch, "run", OTHER).exit_code == 0

        assert len(registry.versions) == 2
        assert {version.name for version in registry.versions} == {PIPELINE, OTHER}
        versions = {version.params["version_hash"] for version in registry.versions}
        assert len(versions) == 1, "byte-identical pipelines hash the same"

    def test_a_plan_registers_nothing(
        self, declared: Path, monkeypatch, registry: FakeVersionRegistry
    ):
        """Counter-example, row 6: the one where nothing was produced.

        `--plan` opens no MLflow run (R11.1 row 5) and produces no artifacts, so
        there is no version. A version registered by a plan would claim a
        pipeline had been run at a hash nobody executed.
        """
        result = _cli(declared, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert registry.registrations == []
