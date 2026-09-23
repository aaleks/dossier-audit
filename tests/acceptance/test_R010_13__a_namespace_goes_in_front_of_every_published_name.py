"""R10.13 — one namespace goes in front of every name dossier publishes into MLflow.

R14.8 gave prompts a per-machine prefix after one checkout's publish arrived as
`v2` of another's. A gold set's dataset has the same global name and a worse
failure -- two workspaces each holding `gold/incidents` merge their records into
one dataset -- and spec 014 recorded it for a person to decide. Decided: one
namespace for both, because two variables are two chances to forget one.

Three harnesses, because the rule makes three claims a person can observe: what a
publish names things, that two workspaces keep two histories, and what an eval
and a run look up afterwards.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.acceptance.test_R014_9__a_judge_links_the_rubric_version_it_judged_with import (
    JudgingModel,
)
from tests.fakes import FakeDatasetRegistry, FakePromptRegistry, FakeTracker
from tests.pipelines import write_pipeline
from tests.scoring_example import PIPELINE

pytestmark = pytest.mark.outer_loop

NAMESPACE = "DOSSIER_MLFLOW_NAMESPACE"
STEPS = ["extract", "verify", "report"]
EXPERIMENT = "dossier-audit/incident-audit/eval/incidents"


def _registries(monkeypatch) -> tuple[FakePromptRegistry, FakeDatasetRegistry]:
    """Tracking on, the eval template rendering `{gold}`, and one server's two registries."""
    import dossier.cli.main as cli

    prompts, datasets = FakePromptRegistry(), FakeDatasetRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setenv("DOSSIER_MLFLOW_EXPERIMENT_EVAL", "dossier-audit/{pipeline}/eval/{gold}")
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: prompts, raising=False
    )
    monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: datasets, raising=False)
    return prompts, datasets


@pytest.fixture
def server(workspace: Path, monkeypatch) -> tuple[FakePromptRegistry, FakeDatasetRegistry]:
    """One server, which every workspace in a test publishes to."""
    write_pipeline(workspace, steps=STEPS, modes={"report": "aggregate"})
    return _registries(monkeypatch)


class TestANamespaceGoesInFrontOfEveryPublishedName:
    """R10.13 — `DOSSIER_MLFLOW_NAMESPACE` in front of every published name."""

    def test_every_prompt_a_publish_sends_carries_the_namespace(
        self, workspace: Path, monkeypatch, server
    ):
        """Row 1: the one where the namespace is in front of every prompt, rubric included."""
        prompts, _ = server
        monkeypatch.setenv(NAMESPACE, "sandbox")

        result = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)

        assert result.exit_code == 0, result.output
        expected = [f"sandbox.{PIPELINE}.{step}" for step in STEPS]
        expected.append(f"sandbox.{PIPELINE}.judge.root_cause")
        assert sorted(prompts.prompts) == sorted(expected)
        assert all(prompts.prompts[name].version == 1 for name in expected)

    def test_a_gold_set_publishes_as_a_namespaced_dataset(
        self, workspace: Path, monkeypatch, server
    ):
        """Row 2: the one this rule was decided for.

        The gold set's own name, with the machine's namespace in front of it.
        """
        _, datasets = server
        monkeypatch.setenv(NAMESPACE, "sandbox")

        result = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert list(datasets.datasets) == ["sandbox.incidents"]
        assert len(datasets.datasets["sandbox.incidents"].records) == 4

    def test_two_workspaces_with_one_gold_set_keep_two_datasets(
        self, workspace: Path, tmp_path: Path, monkeypatch, server
    ):
        """Row 3: the one where, before this rule, the second publish merged into the first.

        Both hold `gold/incidents`, and the document keys they share would have
        been merged onto one another's records.
        """
        _, datasets = server
        other = tmp_path / "other-checkout"
        shutil.copytree(workspace, other)

        monkeypatch.setenv(NAMESPACE, "sandbox")
        first = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)
        monkeypatch.delenv(NAMESPACE)
        second = _cli(other, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)

        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert sorted(datasets.datasets) == ["incidents", "sandbox.incidents"]
        assert len(datasets.datasets["incidents"].records) == 4
        assert len(datasets.datasets["sandbox.incidents"].records) == 4

    def test_an_eval_and_a_run_look_up_under_the_namespace(self, judged_run, monkeypatch):
        """Row 4: the one where every lookup asks for the name a publish would send."""
        import dossier.cli.main as cli

        workspace, _ = judged_run
        judge = JudgingModel({})
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)
        _registries(monkeypatch)
        tracker = FakeTracker()
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
        monkeypatch.setenv(NAMESPACE, "sandbox")
        for publish in (
            ("prompts", "publish", PIPELINE),
            ("dataset", "publish", PIPELINE, "--gold", GOLD),
        ):
            published = _cli(workspace, monkeypatch, *publish)
            assert published.exit_code == 0, published.output

        evaluated = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
        ran = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert evaluated.exit_code == 0, evaluated.output
        assert ran.exit_code == 0, ran.output
        eval_run, run_run = tracker.runs[0], tracker.runs[1]
        assert [held["name"] for held in eval_run.inputs] == ["sandbox.incidents"]
        assert (f"sandbox.{PIPELINE}.judge.root_cause", 1) in tracker.links
        assert (f"sandbox.{PIPELINE}.extract", 1) in tracker.links
        assert run_run.tags.get("dossier.kind") == "run"

    def test_no_namespace_leaves_every_name_as_composed(
        self, workspace: Path, monkeypatch, server
    ):
        """Counter-example (row 5): the one where nothing changes for anyone.

        Published with the variable unset, then again with it empty: the same
        names, so the second publish finds both and sends nothing.
        """
        prompts, datasets = server
        _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
        _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)
        sent = len(prompts.publishes)
        monkeypatch.setenv(NAMESPACE, "")

        again = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
        republished = _cli(
            workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD
        )

        assert again.exit_code == 0, again.output
        assert republished.exit_code == 0, republished.output
        assert f"{PIPELINE}.extract" in prompts.prompts
        assert list(datasets.datasets) == ["incidents"]
        assert len(prompts.publishes) == sent, "nothing sent the second time"

    def test_the_experiment_a_namespaced_dataset_joins_is_unchanged(
        self, workspace: Path, monkeypatch, server
    ):
        """Counter-example (row 6): the one name this machine already templates.

        `{gold}` renders the gold directory, so the experiment is the one an eval
        of this gold set records to, namespace or none (R10.2).
        """
        _, datasets = server
        monkeypatch.setenv(NAMESPACE, "sandbox")

        result = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert datasets.datasets["sandbox.incidents"].experiments == [EXPERIMENT]
