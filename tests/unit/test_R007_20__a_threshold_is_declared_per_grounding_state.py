"""R7.20 — a judged field's agreement threshold is declared per grounding state.

R7.13 gave `judge.yaml` one threshold per judged field, which was right while
there was one way to answer a field. R6.15 added a second: `root_cause` can be
answered from text a search can confirm, or read off a page by a model looking
at it. One bar for both would gate a `described` verdict on a figure measured
against text, which is R7.15's failure with the paperwork in order.

The gold files are the person-written set in `tests/fixtures/gold/incidents/`,
copied into a temporary workspace and never written to in place.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.config.load import ConfigError, load_judge_thresholds, load_pipeline

FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"

JUDGED = "root_cause"
GROUNDED = "grounded"
DESCRIBED = "described"


def _workspace(root: Path, *, judge: str, mode: str = "per_file") -> Path:
    """A pipeline declaring `gold/incidents/`, with `judge.yaml` as given.

    `mode` is what decides whether a `described` verdict can arise at all: a
    `per_part` step is the only thing that hands a stage a picture (R3.12), and
    it has to name the kind it fans out over or R3.12 refuses it outright.
    """
    inputs = {"extract": "documents@page_images"} if mode == "per_part" else {}
    path = write_pipeline(root, modes={"extract": mode}, inputs=inputs)
    path.write_text(
        path.read_text(encoding="utf-8") + "gold: gold/incidents/\n", encoding="utf-8"
    )
    gold = root / "gold" / "incidents"
    shutil.copytree(FIXTURE_GOLD, gold)
    (gold / "judge.yaml").write_text(judge, encoding="utf-8")
    return path


def _thresholds(root: Path) -> dict[str, dict[str, float]]:
    return load_judge_thresholds(root / "gold" / "incidents")


class TestAThresholdIsDeclaredPerGroundingState:
    """R7.20 — one bar per state, and a scalar still means `grounded`."""

    def test_two_states_are_read_as_two_figures(self, tmp_path: Path):
        """Example 1: the one the visual judge needs.

        The two numbers are the two measurements: 0.95 over the text sample,
        0.90 over the visual one. Declaring them separately is the only way a
        reader can check either against what it was measured on.
        """
        _workspace(tmp_path, judge=f"{JUDGED}:\n  {GROUNDED}: 0.95\n  {DESCRIBED}: 0.90\n")

        assert _thresholds(tmp_path) == {JUDGED: {GROUNDED: 0.95, DESCRIBED: 0.90}}

    def test_a_scalar_is_the_grounded_bar(self, tmp_path: Path):
        """Example 2: the one where every gold set written before this loads.

        R3.11's bargain, for the same reason: a shape that breaks every file
        already written buys a consistency nobody asked for. A scalar declares
        nothing about a state the pipeline that wrote it could not produce.
        """
        _workspace(tmp_path, judge=f"{JUDGED}: 0.95\n")

        assert _thresholds(tmp_path) == {JUDGED: {GROUNDED: 0.95}}

    def test_a_per_part_step_needs_a_described_bar(self, tmp_path: Path):
        """Example 3: the one where a verdict could arrive with nothing to gate it.

        Named at load time rather than discovered at scoring time, which is
        after the run has been paid for -- the reasoning R7.13 row 2 already
        applies to a field with no bar at all.
        """
        path = _workspace(tmp_path, judge=f"{JUDGED}: 0.95\n", mode="per_part")

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert JUDGED in str(error.value)
        assert DESCRIBED in str(error.value)

    def test_a_state_nobody_declared_is_refused_by_name(self, tmp_path: Path):
        """Example 4: the one where a bar gates nothing and looks like it does.

        `visual` reads exactly like a threshold somebody agreed to. Nothing
        would ever read it, and the field would be gated on `grounded` alone
        while the file said otherwise.
        """
        path = _workspace(tmp_path, judge=f"{JUDGED}:\n  visual: 0.9\n")

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert "visual" in str(error.value)
        assert GROUNDED in str(error.value) and DESCRIBED in str(error.value)

    def test_a_percentage_is_refused_inside_a_state_too(self, tmp_path: Path):
        """Example 5: the one where the old check has to reach a level deeper.

        R7.13 row 3 refused `95`. A shape change that quietly stopped checking
        the numbers would be a worse regression than the shape was an
        improvement.
        """
        path = _workspace(tmp_path, judge=f"{JUDGED}:\n  {GROUNDED}: 95\n")

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert "95" in str(error.value)

    def test_a_per_file_step_is_not_asked_for_a_bar_it_cannot_use(self, tmp_path: Path):
        """Counter-example 6: the one where asking would be ceremony.

        No step in this pipeline hands a stage a picture, so no described
        verdict can arise. A required bar for one would be a line every author
        copies without meaning it, which is how a threshold stops being agreed.
        """
        path = _workspace(tmp_path, judge=f"{JUDGED}: 0.95\n", mode="per_file")

        config = load_pipeline(path, providers=PROVIDERS)

        assert config.gold == "gold/incidents/"
