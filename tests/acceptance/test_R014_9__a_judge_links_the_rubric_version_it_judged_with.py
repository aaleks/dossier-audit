"""R14.9 — a judge's record links the rubric version it judged with.

R14.7 for the other half of what R14.2 publishes. A run links the prompts it
rendered; an eval and a calibration judge with a rubric, and until this rule
the rubric sat in the registry at version 1 with nothing pointing at it -- found
live, beside a run that linked its prompt exactly as R14.7 says.

The version is found by the rubric's hash, which is the `text_hash` the gate
already compares (R7.15), and not by what is newest. A rubric edited and
republished since would otherwise attach a standard to an eval that was never
judged by it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.conftest import GOLD, URI, _cli
from tests.fakes import FakeModelClient, FakePromptRegistry, FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

RUBRIC = f"{PIPELINE}.judge.root_cause"


class JudgingModel(RoutedModel):
    """A judge that finds every candidate supported, and counts how often it is asked."""

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if "<claim>" in prompt:
            self.calls.append("judge")
            return json.dumps({"supported": True, "evidence": "the stated cause"})
        return super().complete(prompt, schema=schema, parts=parts)


@pytest.fixture
def judge(judged_run, monkeypatch) -> JudgingModel:
    import dossier.cli.bootstrap as cli

    model = JudgingModel({})
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return model


def _wire(monkeypatch) -> tuple[FakePromptRegistry, FakeTracker]:
    """Tracking on, a prompt registry that counts its reads, a tracker that keeps links."""
    import dossier.cli.bootstrap as cli

    registry = FakePromptRegistry()
    tracker = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    monkeypatch.setattr(
        cli, "build_prompt_registry", lambda settings, **_: registry, raising=False
    )
    return registry, tracker


@pytest.fixture
def wired(judge, monkeypatch) -> tuple[FakePromptRegistry, FakeTracker]:
    return _wire(monkeypatch)


def _rubric(workspace: Path) -> Path:
    return workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"


def _publish(workspace: Path, monkeypatch) -> None:
    published = _cli(workspace, monkeypatch, "prompts", "publish", PIPELINE)
    assert published.exit_code == 0, published.output


def _rubric_links(tracker: FakeTracker, name: str = RUBRIC) -> list[tuple[str, int]]:
    return [link for link in tracker.links if link[0] == name]


class TestAJudgeLinksTheRubricVersionItJudgedWith:
    """R14.9 — a judge's MLflow record links the rubric version it judged with."""

    def test_an_eval_links_the_version_carrying_the_rubric_it_judged_with(
        self, judged_run, monkeypatch, wired
    ):
        """Row 1: the one where the newest version is the wrong answer.

        Published, a draft published over it, the draft reverted in the
        checkout. The eval judged with the first words, so the first version is
        what its record links.
        """
        workspace, _ = judged_run
        registry, tracker = wired
        _publish(workspace, monkeypatch)
        original = _rubric(workspace).read_text(encoding="utf-8")
        _rubric(workspace).write_text(original + "\nA draft standard.\n", encoding="utf-8")
        _publish(workspace, monkeypatch)
        _rubric(workspace).write_text(original, encoding="utf-8")

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert registry.prompts[RUBRIC].version == 2, "two versions were published"
        assert _rubric_links(tracker) == [(RUBRIC, 1)], (
            "the eval judged with the first rubric, so it links version 1 and not the newest"
        )

    def test_a_calibration_links_the_rubric_it_measured_once(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where the measurement is *of* the rubric.

        One link for the field, however many judges were measured against it:
        a rubric is one prompt, and a second link to the same version would say
        nothing the first did not.
        """
        calibratable = _calibratable(workspace, monkeypatch)
        registry, tracker = _wire(monkeypatch)
        _publish(calibratable, monkeypatch)
        import dossier.cli.bootstrap as cli

        judge = FakeModelClient(responses=[json.dumps({"supported": v}) for v in VERDICTS])
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)

        result = _cli(calibratable, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert _rubric_links(tracker) == [(RUBRIC, 1)]

    def test_an_eval_served_from_the_judge_cache_links_the_rubric_all_the_same(
        self, judged_run, monkeypatch, judge: JudgingModel, wired
    ):
        """Row 3: the one where nothing was asked and everything was judged.

        The second eval reads every verdict from the cache (R7.18). Those
        verdicts were reached under this rubric, and their key holds its hash,
        so where they were read from is not what the link is about.
        """
        workspace, _ = judged_run
        _, tracker = wired
        _publish(workspace, monkeypatch)
        first = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
        assert first.exit_code == 0, first.output
        asked = len(judge.calls)

        second = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert second.exit_code == 0, second.output
        assert len(judge.calls) == asked, "the second eval asked the judge nothing"
        assert _rubric_links(tracker) == [(RUBRIC, 1), (RUBRIC, 1)], (
            "and linked the rubric exactly as the first did"
        )

    def test_a_prefixed_rubric_is_looked_up_under_its_prefix(
        self, judged_run, monkeypatch, wired
    ):
        """Row 4: the one where the eval asks under the name it would publish under (R10.13)."""
        workspace, _ = judged_run
        _, tracker = wired
        monkeypatch.setenv("DOSSIER_MLFLOW_NAMESPACE", "sandbox")
        _publish(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert _rubric_links(tracker, f"sandbox.{RUBRIC}") == [(f"sandbox.{RUBRIC}", 1)]

    def test_a_withheld_field_asks_nothing_and_links_nothing(
        self, judged_run, monkeypatch, wired
    ):
        """Counter-example (row 5): the one whose rubric moved since it was measured.

        Withheld as stale (R7.15), so nothing was judged with it, and a link
        would name words no reported figure came from.
        """
        workspace, _ = judged_run
        registry, tracker = wired
        _publish(workspace, monkeypatch)
        _rubric(workspace).write_text(
            _rubric(workspace).read_text(encoding="utf-8") + "\nA new standard.\n",
            encoding="utf-8",
        )
        registry.reads.clear()

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert "stale" in result.output, "the field was withheld, which is the premise"
        assert RUBRIC not in registry.reads, "a withheld field's rubric is not looked up"
        assert _rubric_links(tracker) == []

    def test_a_rubric_never_published_links_nothing(self, judged_run, monkeypatch, wired):
        """Counter-example (row 6): the one where the registry has never heard of it.

        Nothing to link, so nothing linked -- and the eval records and exits as
        it would have. Failing an eval because nobody ran `prompts publish` would
        be tracking changing a command, which R10.4 forbids.
        """
        workspace, _ = judged_run
        _, tracker = wired

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert tracker.links == []
        assert "recorded to MLflow" in result.output, "and it recorded as it always did"

    def test_tracking_off_asks_the_registry_nothing(self, judged_run, monkeypatch, wired):
        """Counter-example (row 7): the one where the whole mechanism is absent.

        Not merely "links nothing": the registry is never asked, on either
        command a judge runs under.
        """
        workspace, _ = judged_run
        registry, _ = wired
        _publish(workspace, monkeypatch)
        registry.reads.clear()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "false")

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert registry.reads == [], "tracking off asks the registry nothing"

    def test_a_run_links_no_rubric(self, judged_run, monkeypatch, wired):
        """Counter-example (row 8): the one that judges nothing.

        A run links the prompts it rendered (R14.7) and no rubric: nothing in it
        was judged. A comparison does judge, and links its rubric -- R14.11.
        """
        workspace, _ = judged_run
        _, tracker = wired
        _publish(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _rubric_links(tracker) == []


# Twenty human-scored cases, twelve supported to eight, as R7.11's sample was.
VERDICTS = [True] * 12 + [False] * 8


def _calibratable(workspace: Path, monkeypatch) -> Path:
    """A synced workspace whose gold set carries a bar and a twenty-case sample."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    gold = workspace / "gold" / "incidents"
    (gold / "samples").mkdir(parents=True)
    (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    keys = sorted(ISSUES)
    cases = [
        {
            "document": keys[index % len(keys)],
            "answer": f"candidate answer {index}",
            "supported": supported,
            "verified_by": "a.aleks",
            "verified_at": "2026-09-15",
        }
        for index, supported in enumerate(VERDICTS)
    ]
    (gold / "samples" / "root_cause.jsonl").write_text(
        "\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8"
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace
