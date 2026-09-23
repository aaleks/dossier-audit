"""R14.12 — a pipeline version links the prompt version each of its steps rendered.

R14.7 links a run to the prompts it rendered. The version that run built is made
of exactly those prompts -- its hash is taken over theirs (R13.1) -- and the
Models tab, where two versions are compared, showed none of them. `dossier run`
builds the version, so it links them, from the same lookups R14.7 makes.

A live spike against a real server, before this test was written: MLflow keeps a
logged model's linked prompts in one `mlflow.linkedPrompts` tag, linking the same
version twice leaves one entry, and linking to a model that does not exist
raises `RESOURCE_DOES_NOT_EXIST`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.acceptance.test_R014_9__a_judge_links_the_rubric_version_it_judged_with import (
    JudgingModel,
)
from tests.fakes import FakePromptRegistry, FakeTracker, FakeVersionRegistry, register_connector
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

PROMPT = f"{PIPELINE}.extract"
RUBRIC = f"{PIPELINE}.judge.root_cause"


@pytest.fixture
def declared(workspace: Path, monkeypatch) -> Path:
    """The scoring example's incidents, synced with tracking off."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return workspace


def _wire(monkeypatch) -> tuple[FakePromptRegistry, FakeTracker, FakeVersionRegistry]:
    """Tracking on, with a prompt registry, a tracker and a version registry that count."""
    import dossier.cli.main as cli

    prompts, tracker, versions = FakePromptRegistry(), FakeTracker(), FakeVersionRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: prompts, raising=False
    )
    monkeypatch.setattr(cli, "build_version_registry", lambda settings: versions, raising=False)
    return prompts, tracker, versions


@pytest.fixture
def wired(declared, monkeypatch):
    return _wire(monkeypatch)


def _model(monkeypatch, answers=ANSWERS, *, judge: RoutedModel | None = None) -> RoutedModel:
    import dossier.cli.main as cli

    model = judge or RoutedModel(answers)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return model


def _publish(workspace: Path, monkeypatch) -> None:
    published = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
    assert published.exit_code == 0, published.output


def _prompt(workspace: Path) -> Path:
    return workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"


class TestAPipelineVersionLinksThePromptsItsStepsRendered:
    """R14.12 — the version a run built links the prompt version each step rendered."""

    def test_the_version_links_the_prompt_its_step_rendered(
        self, declared: Path, monkeypatch, wired
    ):
        """Row 1: the one where the Models tab says what a version is made of."""
        _, tracker, versions = wired
        _model(monkeypatch)
        _publish(declared, monkeypatch)

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        [version] = versions.versions
        assert tracker.version_links == [(version.version_id, PROMPT, 1)]
        assert (PROMPT, 1) in tracker.links, "and the run links the same prompt (R14.7)"

    def test_the_version_links_the_prompt_version_carrying_the_hash_it_rendered(
        self, declared: Path, monkeypatch, wired
    ):
        """Row 2: the one where the newest version is the wrong answer."""
        _, tracker, versions = wired
        _model(monkeypatch)
        _publish(declared, monkeypatch)
        original = _prompt(declared).read_text(encoding="utf-8")
        _prompt(declared).write_text(original + "\nBe precise.\n", encoding="utf-8")
        _publish(declared, monkeypatch)
        _prompt(declared).write_text(original, encoding="utf-8")

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        [version] = versions.versions
        assert tracker.version_links == [(version.version_id, PROMPT, 1)]

    def test_a_prompt_published_after_the_run_links_at_the_next_run_of_that_version(
        self, declared: Path, monkeypatch, wired
    ):
        """Row 3: the one completed by a run that cost nothing.

        The second run is every stage a cache hit and no model call, and it is
        the same version -- so the link it adds is to the version the first run
        built, not to a new one.
        """
        _, tracker, versions = wired
        _model(monkeypatch)
        first = _cli(declared, monkeypatch, "run", PIPELINE)
        assert first.exit_code == 0, first.output
        assert tracker.version_links == [], "nothing was published, so nothing linked"
        _publish(declared, monkeypatch)
        model = _model(monkeypatch)

        second = _cli(declared, monkeypatch, "run", PIPELINE)

        assert second.exit_code == 0, second.output
        assert model.call_count == 0, "every stage a cache hit"
        [version] = versions.versions
        assert tracker.version_links == [(version.version_id, PROMPT, 1)]

    def test_a_rubric_is_not_linked_to_the_version(self, declared: Path, monkeypatch, wired):
        """Counter-example (row 4): the one that scores the answers rather than making them."""
        prompts, tracker, _ = wired
        _model(monkeypatch)
        _publish(declared, monkeypatch)
        assert RUBRIC in prompts.prompts, "the rubric is published, which is the premise"

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert [name for _, name, _ in tracker.version_links] == [PROMPT]

    def test_an_eval_links_no_step_prompt_to_the_version(self, judged_run, monkeypatch):
        """Counter-example (row 5): the one that measured a version it did not make."""
        workspace, _ = judged_run
        _model(monkeypatch, judge=JudgingModel({}))
        _, tracker, versions = _wire(monkeypatch)
        _publish(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert versions.versions, "the eval registered the version it scored (R13.2)"
        assert tracker.version_links == []

    def test_no_version_registry_costs_the_version_link_and_nothing_else(
        self, declared: Path, monkeypatch, wired
    ):
        """Counter-example (row 6): the one where the server cannot hold a logged model."""
        import dossier.cli.main as cli

        _, tracker, _ = wired
        _model(monkeypatch)
        _publish(declared, monkeypatch)
        monkeypatch.setattr(cli, "_versions_for", lambda workspace: None)

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert tracker.version_links == []
        assert (PROMPT, 1) in tracker.links, "the run still links its prompt (R14.7)"

    def test_tracking_off_asks_the_registry_nothing(self, declared: Path, monkeypatch, wired):
        """Counter-example (row 7): the one where the whole mechanism is absent."""
        prompts, _, _ = wired
        _model(monkeypatch)
        _publish(declared, monkeypatch)
        prompts.reads.clear()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert prompts.reads == []
