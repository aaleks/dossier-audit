"""R7.23 — a judged field is reported only when every state it can produce clears.

A field's percentage mixes grounded verdicts and described ones. A figure
printed while one half was never measured is the number R7.5 exists to refuse,
arrived at more elaborately -- and "0.82, of which the described verdicts are
ungated" is a number every reader will quote without the clause.

The gate is the CLI's, because the reads are: the rubrics, `judge.yaml`, and one
calibration file per state. What it *decides* with them is `withholding`'s, in
the domain, and is already proved there.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.application.eval import CALIBRATIONS_DIR, judge_prompt_hash
from dossier.cli.eval import _judge_gate
from dossier.config.load import load_pipeline
from dossier.domain.grounding import DESCRIBED, GROUNDED, judge_name, judged_states
from dossier.domain.hashing import text_hash

FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"

JUDGED = "root_cause"
MODEL = "anthropic:claude-sonnet-4-5-20250929"

BOTH_BARS = f"{JUDGED}:\n  {GROUNDED}: 0.95\n  {DESCRIBED}: 0.90\n"


@pytest.fixture
def workspace_with_gold(tmp_path: Path):
    """A `per_part` pipeline declaring a gold set with both bars agreed."""

    def build(*, judge: str = BOTH_BARS, mode: str = "per_part"):
        inputs = {"extract": "documents@page_images"} if mode == "per_part" else {}
        path = write_pipeline(tmp_path, modes={"extract": mode}, inputs=inputs)
        path.write_text(
            path.read_text(encoding="utf-8") + "gold: gold/incidents/\n", encoding="utf-8"
        )
        gold = tmp_path / "gold" / "incidents"
        shutil.copytree(FIXTURE_GOLD, gold, dirs_exist_ok=True)
        (gold / "judge.yaml").write_text(judge, encoding="utf-8")
        return path, gold

    return build


def _calibrate(gold: Path, pipeline: Path, *, state: str, agreement: float) -> None:
    """Write a calibration for one state, as `dossier calibrate` would (R7.14)."""
    rubric = pipeline.parent / "rubrics" / "root_cause.md"
    path = gold / CALIBRATIONS_DIR / f"{judge_name(JUDGED, state)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "judge_model": MODEL,
                "rubric_hash": text_hash(rubric),
                "prompt_hash": judge_prompt_hash(),
                "agreement": agreement,
                "sample_size": 22,
            }
        ),
        encoding="utf-8",
    )


def _gate(pipeline: Path, gold: Path, config):
    return _judge_gate(
        gold,
        pipeline.parent / "schemas" / "incident.yaml",
        pipeline.parent,
        MODEL,
        states=judged_states(per_part=any(s.mode == "per_part" for s in config.steps)),
    )


class TestAFieldIsReportedOnlyWhenEveryStateClears:
    """R7.23 — withheld whole, and the reason names the state."""

    def test_both_states_clear_and_the_field_is_reported(self, workspace_with_gold):
        """Example 1: the one where the visual judge is measured and good enough."""
        pipeline, gold = workspace_with_gold()
        _calibrate(gold, pipeline, state=GROUNDED, agreement=0.97)
        _calibrate(gold, pipeline, state=DESCRIBED, agreement=0.95)

        judges, withheld = _gate(pipeline, gold, load_pipeline(pipeline, providers=PROVIDERS))

        assert withheld == {}
        assert set(judges) == {JUDGED, f"{JUDGED}.{DESCRIBED}"}

    def test_an_unmeasured_described_judge_withholds_the_whole_field(self, workspace_with_gold):
        """Example 2: the one this rule exists for.

        The grounded half is measured and clear. Reporting the field anyway
        would print a percentage covering verdicts from a judge nobody has
        measured -- which is R7.5's failure, reached by a longer route.
        """
        pipeline, gold = workspace_with_gold()
        _calibrate(gold, pipeline, state=GROUNDED, agreement=0.97)

        _, withheld = _gate(pipeline, gold, load_pipeline(pipeline, providers=PROVIDERS))

        assert JUDGED in withheld
        assert DESCRIBED in withheld[JUDGED]
        assert "never measured" in withheld[JUDGED]

    def test_a_described_judge_below_its_bar_is_named_with_the_state(self, workspace_with_gold):
        """Example 3: the one where a measured judge is not good enough.

        A different fix from "never measured", so a different message: this one
        wants a better judge or a figure somebody agrees to lower (R7.15).
        """
        pipeline, gold = workspace_with_gold()
        _calibrate(gold, pipeline, state=GROUNDED, agreement=0.97)
        _calibrate(gold, pipeline, state=DESCRIBED, agreement=0.86)

        _, withheld = _gate(pipeline, gold, load_pipeline(pipeline, providers=PROVIDERS))

        assert DESCRIBED in withheld[JUDGED]
        assert "0.86" in withheld[JUDGED]
        assert "0.9" in withheld[JUDGED]

    def test_a_failing_grounded_half_withholds_it_too(self, workspace_with_gold):
        """Example 4: either half failing makes the one number untrustworthy."""
        pipeline, gold = workspace_with_gold()
        _calibrate(gold, pipeline, state=GROUNDED, agreement=0.80)
        _calibrate(gold, pipeline, state=DESCRIBED, agreement=0.95)

        _, withheld = _gate(pipeline, gold, load_pipeline(pipeline, providers=PROVIDERS))

        assert JUDGED in withheld
        assert "0.8" in withheld[JUDGED]

    def test_a_per_file_pipeline_consults_only_the_grounded_bar(self, workspace_with_gold):
        """Counter-example 5: the one where a described bar would gate nothing.

        No step here can hand a stage a picture, so no described verdict can
        arise. A missing described calibration is not a reason to withhold
        anything, and asking for one would be ceremony (R7.20 row 6).
        """
        pipeline, gold = workspace_with_gold(judge=f"{JUDGED}: 0.95\n", mode="per_file")
        _calibrate(gold, pipeline, state=GROUNDED, agreement=0.97)

        _, withheld = _gate(pipeline, gold, load_pipeline(pipeline, providers=PROVIDERS))

        assert withheld == {}
