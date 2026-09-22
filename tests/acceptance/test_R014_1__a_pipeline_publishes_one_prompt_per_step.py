"""R14.1 — every step of a pipeline publishes as one prompt named `<pipeline>.<step id>`.

The outer loop for spec 014. What a person observes is a command they can run
against a pipeline they already have, before any run exists and before anything
has been synced: publishing prompts is not running them, and needs neither a
document nor a model call.

The names are the whole claim. A prompt name is global in MLflow while a prompt
file is resolved against the pipeline's own directory (spec 005), so the name
carries the pipeline; and it carries the step id rather than the file's name
because a prompt is named for the job it does. Both halves are observable here:
two pipelines holding byte-identical prompt files publish two prompts, and two
steps naming one file publish two prompts.

Tracking is switched on the way a person switches it on, in the environment
(R10.1). The registry is handed in through the same seam `build_tracker`,
`build_model_client` and `build_dataset_registry` use, and it counts, because
R14.1 is a claim about how many prompts exist afterwards rather than about what
came back from making them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakePromptRegistry
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
STEPS = ["extract", "verify", "report"]
URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def registry(workspace: Path, monkeypatch) -> FakePromptRegistry:
    """Tracking on, and a prompt registry that counts what it was told."""
    import dossier.cli.main as cli

    holder = FakePromptRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: holder, raising=False
    )
    write_pipeline(workspace, steps=STEPS, modes={"report": "aggregate"})
    return holder


class TestAPipelinePublishesOnePromptPerStep:
    """R14.1 — every step of a pipeline publishes as one prompt named `<pipeline>.<step id>`."""

    def test_each_step_publishes_one_prompt_named_for_the_pipeline_and_the_step(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Example 1: the one where three steps become three prompts a person can open.

        The dot is not a preference: MLflow rejects `/` and `:` in a prompt name,
        so `incident-audit/verify` was never available. One version each, because
        nothing was there before this publish.
        """
        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 0, result.output
        for step in STEPS:
            name = f"{PIPELINE}.{step}"
            assert name in registry.prompts, f"{name} was not published"
            assert registry.prompts[name].version == 1, f"{name} should hold one version"

    def test_the_terminal_names_each_prompt_with_its_hash_and_version(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Example 1, second half: the one where a person sees what was published.

        Without opening MLflow at all. The hash is what ties a version to the
        provenance record of the run that rendered it (R14.3), so it is on the
        line rather than only in the registry.
        """
        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 0, result.output
        for step in STEPS:
            name = f"{PIPELINE}.{step}"
            assert name in result.output
            published = registry.prompts[name].versions[-1]
            assert published["tags"]["dossier.prompt_hash"][:8] in result.output

    def test_a_second_pipeline_sharing_a_prompt_file_publishes_its_own_prompt(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Example 2: the one where two pipelines hold the same words.

        `postmortem-review`'s `verify` prompt is byte-identical to
        `incident-audit`'s, and it is still a second prompt: a name is global in
        MLflow, and one shared file must not become one shared version history
        into which two pipelines interleave unrelated edits.
        """
        write_pipeline(workspace, name="postmortem-review", steps=["verify"])
        shared = (workspace / "pipelines" / PIPELINE / "prompts" / "verify.md").read_bytes()
        other = workspace / "pipelines" / "postmortem-review" / "prompts" / "verify.md"
        assert other.read_bytes() == shared, "the two files must start identical"

        first = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
        second = _cli(workspace, monkeypatch, "prompts", "publish", "postmortem-review")

        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert f"{PIPELINE}.verify" in registry.prompts
        assert "postmortem-review.verify" in registry.prompts
        assert registry.prompts[f"{PIPELINE}.verify"].version == 1
        assert registry.prompts["postmortem-review.verify"].version == 1

    def test_two_steps_naming_one_file_publish_one_prompt_each(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Example 3: the one where a prompt is named for the job, not the file.

        `verify` is pointed at `extract`'s prompt file. Two steps, two prompts,
        because the alternative — naming by path — puts a rename into the version
        history of a prompt whose text never changed.
        """
        directory = workspace / "pipelines" / PIPELINE
        configuration = directory / "pipeline.yaml"
        configuration.write_text(
            configuration.read_text(encoding="utf-8").replace(
                "prompt: prompts/verify.md", "prompt: prompts/extract.md"
            ),
            encoding="utf-8",
        )
        (directory / "prompts" / "verify.md").unlink()

        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 0, result.output
        assert f"{PIPELINE}.extract" in registry.prompts
        assert f"{PIPELINE}.verify" in registry.prompts
        extract = registry.prompts[f"{PIPELINE}.extract"].versions[-1]
        verify = registry.prompts[f"{PIPELINE}.verify"].versions[-1]
        assert extract["template"] == verify["template"], "one file, two prompts"

    def test_a_step_naming_a_prompt_file_that_is_not_there_publishes_nothing(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Counter-example (row 4): the one where the publish gets no further than a run would.

        R3.6 already refuses this pipeline at load time. A publish reads the
        pipeline the run reads, so it is refused in the same place and for the
        same reason — and it must not send the two prompts it could have read
        before reaching the one it could not.
        """
        (workspace / "pipelines" / PIPELINE / "prompts" / "verify.md").unlink()

        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "prompts/verify.md" in result.output
        assert registry.prompts == {}, "nothing published"
        assert registry.publishes == [], "nothing sent"
