"""R14.8 — a configured prompt prefix goes in front of every prompt name.

The outer loop for the namespace a prompt name was missing. A name carries its
pipeline, which makes it unique within one workspace and no further: two
checkouts holding a pipeline called `incident-audit` publish into one history,
each edit landing as the next version of the other's prompt. That was found
live, after R14.1 was MET, which is why this rule exists.

Two harnesses, because the rule makes two claims a person can observe: what a
publish names things (the pipeline alone is enough), and what a run looks up
afterwards (which needs a synced workspace and a model, as R14.7's test does).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakePromptRegistry, FakeTracker, register_connector
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

PREFIX = "DOSSIER_MLFLOW_PROMPT_PREFIX"
URI = "http://localhost:5000"
STEPS = ["extract", "verify", "report"]


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _tracking_on(monkeypatch, registry: FakePromptRegistry) -> None:
    import dossier.cli.main as cli

    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: registry, raising=False
    )


@pytest.fixture
def registry(workspace: Path, monkeypatch) -> FakePromptRegistry:
    """One server, which every workspace in a test publishes to."""
    holder = FakePromptRegistry()
    _tracking_on(monkeypatch, holder)
    write_pipeline(workspace, steps=STEPS, modes={"report": "aggregate"})
    return holder


class TestAPromptPrefixNamespacesEveryPublishedName:
    """R14.8 — what a publish names things, with and without a prefix."""

    def test_every_name_a_publish_sends_carries_the_prefix(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Row 1: the one where the namespace is in front of every name, rubric included.

        Four prompts, because the rubric `root_cause` is judged against is a
        prompt too (R14.2) and has no less claim to a namespace than a step does.
        """
        monkeypatch.setenv(PREFIX, "sandbox")

        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 0, result.output
        expected = [f"sandbox.{PIPELINE}.{step}" for step in STEPS]
        expected.append(f"sandbox.{PIPELINE}.judge.root_cause")
        assert sorted(registry.prompts) == sorted(expected)
        assert all(registry.prompts[name].version == 1 for name in expected)
        for name in expected:
            assert name in result.output, f"the terminal should name {name}"

    def test_two_workspaces_with_one_pipeline_name_keep_two_histories(
        self, workspace: Path, tmp_path: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Row 2: the one this rule exists for.

        The same pipeline name in two checkouts, one namespaced and one not. Two
        prompts at version 1 each -- where, before this rule, the second publish
        arrived as version 2 of the first workspace's prompt.
        """
        other = tmp_path / "other-checkout"
        write_pipeline(other, steps=STEPS, modes={"report": "aggregate"})
        prompt = other / "pipelines" / PIPELINE / "prompts" / "extract.md"
        prompt.write_text(
            prompt.read_text(encoding="utf-8") + "\nA different team's words.\n",
            encoding="utf-8",
        )

        monkeypatch.setenv(PREFIX, "sandbox")
        first = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
        monkeypatch.delenv(PREFIX)
        second = _cli(other, monkeypatch, "prompts", "publish", PIPELINE)

        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert registry.prompts[f"sandbox.{PIPELINE}.extract"].version == 1
        assert registry.prompts[f"{PIPELINE}.extract"].version == 1, (
            "one history per workspace, not one edit interleaved into the other's"
        )

    def test_an_empty_prefix_is_no_prefix_and_finds_what_was_published_before(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Counter-example (row 4): the one where nothing changes for anyone.

        Published with no prefix, then again with the variable set to nothing.
        Same names, so the second publish finds its history, compares and sends
        nothing (R14.4) -- a namespace that appeared when a variable was merely
        present would split every existing history in two.
        """
        first = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
        sent = len(registry.publishes)
        monkeypatch.setenv(PREFIX, "")
        second = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert f"{PIPELINE}.extract" in registry.prompts
        assert len(registry.publishes) == sent, "nothing sent the second time"

    def test_a_prefix_mlflow_cannot_hold_is_refused_naming_it(
        self, workspace: Path, monkeypatch, registry: FakePromptRegistry
    ):
        """Counter-example (row 5): the one where the namespace is not a name MLflow takes.

        Refused by dossier, naming the character and the variable to fix, before
        anything is sent -- not by an MLflow traceback after three prompts of four
        have already gone.
        """
        monkeypatch.setenv(PREFIX, "team/a")

        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "/" in result.output
        assert PREFIX in result.output
        assert registry.publishes == [], "nothing sent"


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """The scoring example's incidents, synced and ready to run."""
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
def running(synced: Path, monkeypatch):
    """Tracking on, a registry and a tracker that count, and a model that answers."""
    import dossier.cli.main as cli

    registry = FakePromptRegistry()
    tracker = FakeTracker()
    _tracking_on(monkeypatch, registry)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    return registry, tracker


class TestARunLooksUpUnderTheNameItWouldPublishUnder:
    """R14.8 — what a run finds, when the machine it runs on has a prefix or not."""

    def test_a_run_links_the_prefixed_version(self, synced: Path, monkeypatch, running):
        """Row 3: the one where publishing and linking agree because both ask one name."""
        registry, tracker = running
        monkeypatch.setenv(PREFIX, "sandbox")
        assert _cli(synced, monkeypatch, "prompts", "publish", PIPELINE).exit_code == 0

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert (f"sandbox.{PIPELINE}.extract", 1) in tracker.links

    def test_a_run_on_a_machine_without_the_prefix_links_nothing(
        self, synced: Path, monkeypatch, running
    ):
        """Counter-example (row 6): the one a per-machine setting cannot help.

        Published under `sandbox`, run with no prefix. The run looks up the
        unprefixed name, finds nothing, links nothing -- and exits exactly as it
        would have, because tracking may not change what a run does (R14.7 row 2).
        """
        registry, tracker = running
        monkeypatch.setenv(PREFIX, "sandbox")
        assert _cli(synced, monkeypatch, "prompts", "publish", PIPELINE).exit_code == 0
        monkeypatch.delenv(PREFIX)

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert tracker.links == [], "the name this machine asks for was never published"
