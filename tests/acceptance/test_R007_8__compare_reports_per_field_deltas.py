"""R7.8 — `--compare` scores both configurations over the same documents and flags
every regression.

The change gate. Prompt, model and converter changes all pass through it, and a
change that raises the overall figure can still make one field worse -- which a
single number would hide. A configuration is named by the run that used it:
`a` and `b` are run ids, each reproduced from its own manifest and cache, so the
comparison asks no model.

Run `a` is `_fixtures.md`'s scoring example and run `b` its comparison example:
the same four documents, the prompt edited in between so that `b` is asked
afresh. The gold set is the person-written one in `tests/fixtures/gold/incidents/`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ANSWERS_AFTER,
    FIELDS,
    FIFTH_ISSUE,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.application.eval import judge_prompt_hash
from dossier.domain.hashing import text_hash

# R7.8 examples 1, 2 and 4, transcribed from `_fixtures.md`: `a`, `b`, delta.
EXPECTED = {
    "loss_amount": ("100.0%", "100.0%", "+0.0"),
    "resolution_date": ("75.0%", "100.0%", "+25.0"),
    "severity": ("100.0%", "100.0%", "+0.0"),
    "affected_systems": ("75.0%", "50.0%", "-25.0"),
    "root_cause": ("50.0%", "100.0%", "+50.0"),
}


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _run(workspace: Path, monkeypatch, answers) -> str:
    """Execute the pipeline with a model scripted to `answers`; return the run id."""
    import dossier.cli.main as cli

    model = RoutedModel(answers)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    assert model.call_count > 0, "the prompt changed, so the model must be asked afresh"
    return re.search(r"^run (\S+)", result.output, re.MULTILINE).group(1)


def _edit_prompt(workspace: Path) -> None:
    """A prompt change, as a person tuning the pipeline would make one.

    The placeholders stay as they are (R3.6); the wording moves, and with it the
    stage key, so the next run asks the model again (R5.2).
    """
    prompt = workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"
    prompt.write_text(
        "Read carefully; cite only what the document states.\n"
        + prompt.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _compare(workspace: Path, monkeypatch, a: str, b: str):
    return _cli(
        workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents", "--compare", a, b
    )


def _field_lines(output: str) -> dict[str, str]:
    lines: dict[str, str] = {}
    for line in output.splitlines():
        words = line.split()
        if words and words[0] in FIELDS:
            lines[words[0]] = line
    return lines


def _row(line: str) -> tuple[str, ...]:
    """A field's two scores and its signed delta, as the report prints them."""
    scores = re.findall(r"\d+\.\d%", line)
    delta = re.findall(r"(?<!\S)[+-]\d+\.\d(?!\S)", line)
    return (*scores, *delta)


@pytest.fixture
def tracker(workspace: Path, monkeypatch) -> IssueTracker:
    """The four incidents, held and ready to run."""
    source = IssueTracker(ISSUES)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: source)
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    # The judge is calibrated, so `root_cause` may be reported on both sides
    # (R7.15, R7.17 row 7). Every gold `root_cause` here is null, so no judge is
    # asked: the comparison still asks no model.
    gold = workspace / "gold" / "incidents"
    (gold / "calibrations").mkdir(parents=True, exist_ok=True)
    (gold / "calibrations" / "root_cause.json").write_text(
        json.dumps(
            {
                "judge_model": RoutedModel.model_id,
                "rubric_hash": text_hash(
                    workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"
                ),
                "prompt_hash": judge_prompt_hash(),
                "agreement": 1.0,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return source


@pytest.fixture
def two_runs(workspace: Path, monkeypatch, tracker: IssueTracker) -> tuple[str, str]:
    """Run `a`, the prompt edited, then run `b` -- over the same four documents."""
    import dossier.cli.main as cli

    a = _run(workspace, monkeypatch, ANSWERS)
    _edit_prompt(workspace)
    b = _run(workspace, monkeypatch, ANSWERS_AFTER)

    # Comparing asks no model: both runs are reproduced from their cache entries.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return a, b


class TestCompareReportsPerFieldDeltas:
    """R7.8 — `--compare` scores both runs over the same documents and flags every
    regression."""

    def test_each_field_is_listed_with_both_scores_and_the_delta(
        self, workspace: Path, monkeypatch, two_runs: tuple[str, str]
    ):
        """Example 1: the one where runs `a` and `b` cover the scoring example's documents."""
        result = _compare(workspace, monkeypatch, *two_runs)

        assert result.exit_code == 0, result.output
        lines = _field_lines(result.output)
        assert {field: _row(lines.get(field, "")) for field in FIELDS} == EXPECTED

    def test_a_field_that_got_worse_is_flagged_even_though_overall_improved(
        self, workspace: Path, monkeypatch, two_runs: tuple[str, str]
    ):
        """Example 2: the one where `affected_systems` falls 75.0% to 50.0% under a
        better overall figure.

        80.0% to 90.0% reads as a win. The field that regressed is what someone
        has to go and fix, so it is the one that must stand out.
        """
        result = _compare(workspace, monkeypatch, *two_runs)

        assert result.exit_code == 0, result.output
        overall = [line for line in result.output.splitlines() if "overall" in line]
        assert overall and "80.0%" in overall[0] and "90.0%" in overall[0], overall
        lines = _field_lines(result.output)
        assert [field for field, line in lines.items() if "regression" in line] == [
            "affected_systems"
        ]

    def test_runs_over_different_documents_are_refused(
        self, workspace: Path, monkeypatch, tracker: IssueTracker
    ):
        """Example 3: the one where run `b` also covers `INC-5102`, which run `a` did not.

        Scores over different documents are not comparable: a field can move
        because the documents did. Refused, naming what differs, before anything
        is scored.
        """
        a = _run(workspace, monkeypatch, ANSWERS)
        tracker.issues.update(FIFTH_ISSUE)
        synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
        assert synced.exit_code == 0, synced.output
        _edit_prompt(workspace)
        b = _run(workspace, monkeypatch, ANSWERS_AFTER)

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code != 0
        assert "INC-5102" in result.output

    def test_runs_that_pinned_the_same_documents_but_scored_different_ones_are_refused(
        self, workspace: Path, monkeypatch, tracker: IssueTracker
    ):
        """Example 4: the one where run `b` produced nothing for `INC-5455`.

        Both runs pinned the same four documents, so comparing on what was
        *pinned* would have compared four scores against three and called the
        difference an effect of the prompt. The comparison is over what each run
        scored -- pinned, less what it recorded producing nothing for (R4.13,
        R7.20).
        """
        failing = "INC-5455"

        class PartlyUnusable(RoutedModel):
            def complete(self, prompt: str, *, schema: dict | None = None) -> str:
                if f"# {failing}\n" in prompt:
                    self.calls.append(failing)
                    return "The figures were reviewed and look right."
                return super().complete(prompt, schema=schema)

        import dossier.cli.main as cli

        a = _run(workspace, monkeypatch, ANSWERS)
        _edit_prompt(workspace)
        model = PartlyUnusable(ANSWERS_AFTER)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
        partial = _cli(workspace, monkeypatch, "run", PIPELINE)
        assert partial.exit_code == 1, partial.output
        b = re.search(r"^run (\S+)", partial.output, re.MULTILINE).group(1)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code != 0
        assert failing in result.output

    def test_a_field_that_did_not_move_is_reported_with_a_delta_of_zero(
        self, workspace: Path, monkeypatch, two_runs: tuple[str, str]
    ):
        """Counter-example (row 4): the one where `severity` is 100.0% in both runs.

        Reported, not omitted. A silent row is indistinguishable from a missing
        one, and a missing one is a field nobody scored.
        """
        result = _compare(workspace, monkeypatch, *two_runs)

        assert result.exit_code == 0, result.output
        assert _row(_field_lines(result.output).get("severity", "")) == (
            "100.0%",
            "100.0%",
            "+0.0",
        )
