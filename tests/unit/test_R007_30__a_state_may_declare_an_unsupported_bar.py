"""R7.30 — `judge.yaml` may declare, per grounding state, the share of unsupported
cases a judge must catch.

R7.28 reports the two halves of a calibration apart because agreement pools
them: a judge at 90% can have let two invented causes through. Catching an
unsupported claim is the judge's whole job (R7.12), so that half may carry a
bar of its own -- declared where every bar is, with the gold set, by a person
(R7.13), and optional, so every file written before it loads unchanged.

The gold files are the person-written set in `tests/fixtures/gold/incidents/`,
copied into a temporary workspace and never written to in place.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.config.load import (
    ConfigError,
    load_judge_thresholds,
    load_pipeline,
    load_unsupported_bars,
)

FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"


def _workspace(root: Path, *, judge: str, mode: str = "per_file") -> Path:
    """A pipeline declaring `gold/incidents/`, with `judge.yaml` as given."""
    inputs = {"extract": "documents@page_images"} if mode == "per_part" else {}
    path = write_pipeline(root, modes={"extract": mode}, inputs=inputs)
    path.write_text(
        path.read_text(encoding="utf-8") + "gold: gold/incidents/\n", encoding="utf-8"
    )
    gold = root / "gold" / "incidents"
    shutil.copytree(FIXTURE_GOLD, gold)
    (gold / "judge.yaml").write_text(judge, encoding="utf-8")
    return path


def _gold(root: Path) -> Path:
    return root / "gold" / "incidents"


class TestAStateMayDeclareAnUnsupportedBar:
    """R7.30 — beside the agreement bar, never instead of it."""

    def test_a_state_declares_both_bars(self, tmp_path: Path):
        """Row 1: the one with both bars for `grounded`."""
        _workspace(
            tmp_path, judge="root_cause:\n  grounded: {agreement: 0.95, unsupported: 0.875}\n"
        )

        assert load_judge_thresholds(_gold(tmp_path)) == {"root_cause": {"grounded": 0.95}}
        assert load_unsupported_bars(_gold(tmp_path)) == {"root_cause": {"grounded": 0.875}}

    def test_each_state_declares_its_own(self, tmp_path: Path):
        """Row 2: the one where only the page judge carries an unsupported bar.

        A text judge and a page judge are two judges (R7.20); a bar for one says
        nothing about the other.
        """
        path = _workspace(
            tmp_path,
            judge=(
                "root_cause:\n"
                "  grounded: 0.95\n"
                "  described: {agreement: 0.90, unsupported: 0.875}\n"
            ),
            mode="per_part",
        )

        load_pipeline(path, providers=PROVIDERS)
        assert load_judge_thresholds(_gold(tmp_path)) == {
            "root_cause": {"grounded": 0.95, "described": 0.90}
        }
        assert load_unsupported_bars(_gold(tmp_path)) == {"root_cause": {"described": 0.875}}

    def test_a_file_written_before_this_rule_declares_no_unsupported_bar(self, tmp_path: Path):
        """Row 3: the one written before this rule -- a scalar, loaded as it was."""
        _workspace(tmp_path, judge="root_cause: 0.95\n")

        assert load_judge_thresholds(_gold(tmp_path)) == {"root_cause": {"grounded": 0.95}}
        assert load_unsupported_bars(_gold(tmp_path)) == {}

    def test_a_percentage_is_refused_by_name(self, tmp_path: Path):
        """Row 4: the one with 87.5 for 0.875 -- a proportion is a proportion (R7.13 row 3)."""
        _workspace(
            tmp_path, judge="root_cause:\n  grounded: {agreement: 0.95, unsupported: 87.5}\n"
        )

        with pytest.raises(ConfigError) as refused:
            load_unsupported_bars(_gold(tmp_path))

        message = str(refused.value)
        assert "'root_cause'" in message
        assert "grounded" in message
        assert "unsupported" in message
        assert "87.5" in message

    def test_a_bar_under_a_name_nothing_reads_is_refused(self, tmp_path: Path):
        """Row 5: the one with a `supported` bar, which gates nothing.

        Only the unsupported half has a bar of its own: a judge that rejects a
        true cause costs a point of score, one that accepts an invented cause
        reports a wrong answer as right.
        """
        _workspace(
            tmp_path, judge="root_cause:\n  grounded: {agreement: 0.95, supported: 0.9}\n"
        )

        with pytest.raises(ConfigError) as refused:
            load_judge_thresholds(_gold(tmp_path))

        message = str(refused.value)
        assert "'supported'" in message
        assert "agreement" in message and "unsupported" in message

    def test_an_unsupported_bar_never_stands_in_for_the_agreement_bar(self, tmp_path: Path):
        """Row 6, counter-example: the one with an unsupported bar and no agreement bar."""
        _workspace(tmp_path, judge="root_cause:\n  grounded: {unsupported: 0.875}\n")

        with pytest.raises(ConfigError) as refused:
            load_judge_thresholds(_gold(tmp_path))

        message = str(refused.value)
        assert "'root_cause'" in message
        assert "agreement" in message
