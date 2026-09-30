"""R7.31 — a judged field is withheld when its judge caught fewer of the
unsupported cases than the bar asks.

Agreement pools the two halves of a sample, so a judge can clear its agreement
bar and still let invented causes through. With an unsupported bar declared
(R7.30), that half is compared on its own: at or above the bar, from at least
eight cases, and from a calibration that counted them at all.

What the gate *decides* is `withholding`'s, in the domain, proved here with a
`Calibration` and no workspace. The last test proves the CLI's gate reads the
bar and hands it over, because a rule proved one layer below the command that
promises it is the failure R11.3 and R11.4 once shipped with.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from tests.pipelines import PROVIDERS, write_pipeline

from dossier.application.eval import CALIBRATIONS_DIR, judge_prompt_hash
from dossier.cli.eval import judge_gate
from dossier.config.load import load_pipeline
from dossier.domain.grounding import DESCRIBED, GROUNDED, judge_name, judged_states
from dossier.domain.hashing import text_hash
from dossier.domain.judges import Calibration, Tally, withholding

MODEL = "openai:gpt-5.4-mini"
RUBRIC_HASH = "f7a2d9c4"
PROMPT_HASH = "0443845a"
FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"


def _measured(
    agreement: float, *, unsupported: Tally | None, supported: Tally | None = None
) -> Calibration:
    counted = unsupported is not None
    return Calibration(
        judge_model=MODEL,
        rubric_hash=RUBRIC_HASH,
        prompt_hash=PROMPT_HASH,
        agreement=agreement,
        sample_size=20,
        lower_bound=0.5 if counted else None,
        kappa=0.8 if counted else None,
        supported=(supported or Tally(agreed=12, cases=12)) if counted else None,
        unsupported=unsupported,
    )


def _withheld(calibration: Calibration, *, threshold: float, unsupported: float | None):
    return withholding(
        calibration,
        judge_model=MODEL,
        rubric_hash=RUBRIC_HASH,
        prompt_hash=PROMPT_HASH,
        threshold=threshold,
        unsupported=unsupported,
    )


class TestAJudgeThatLetsClaimsThroughIsWithheld:
    """R7.31 — the unsupported half, compared on its own."""

    def test_exactly_at_the_bar_is_reported(self):
        """Row 1: the one exactly at the bar -- 7 of 8 meets 0.875, inclusive as R7.5 is."""
        calibration = _measured(0.95, unsupported=Tally(agreed=7, cases=8))

        assert _withheld(calibration, threshold=0.95, unsupported=0.875) is None

    def test_more_cases_than_the_minimum_and_above_the_bar_is_reported(self):
        """Row 7: the one with 11 of 12 caught -- past the minimum of 8, and above 0.875."""
        calibration = _measured(0.95, unsupported=Tally(agreed=11, cases=12))

        assert _withheld(calibration, threshold=0.95, unsupported=0.875) is None

    def test_a_judge_that_clears_its_agreement_and_lets_claims_through_is_withheld(self):
        """Row 2: exercise 10's described judge -- 90% against 0.90, 6 of 8 caught."""
        calibration = _measured(0.90, unsupported=Tally(agreed=6, cases=8))

        assert _withheld(calibration, threshold=0.90, unsupported=None) is None
        assert (
            _withheld(calibration, threshold=0.90, unsupported=0.875)
            == "unsupported 6 of 8 (75.0%) is below the agreed 87.5%"
        )

    def test_too_few_unsupported_cases_is_not_measurable(self):
        """Row 3: the one with seven unsupported cases, all caught -- never 100%."""
        calibration = _measured(1.0, unsupported=Tally(agreed=7, cases=7))

        reason = _withheld(calibration, threshold=0.95, unsupported=0.875)

        assert reason is not None
        assert "7" in reason and "8" in reason
        assert "100" not in reason

    def test_a_calibration_from_before_the_counts_is_measured_again(self):
        """Row 4: the one measured before its unsupported cases were counted."""
        calibration = _measured(1.0, unsupported=None)

        reason = _withheld(calibration, threshold=0.95, unsupported=0.875)

        assert reason is not None
        assert "dossier calibrate" in reason

    def test_the_agreement_is_checked_first(self):
        """Row 5: the one below its agreement bar -- withheld on the agreement, as today."""
        calibration = _measured(0.85, unsupported=Tally(agreed=6, cases=8))

        assert (
            _withheld(calibration, threshold=0.90, unsupported=0.875)
            == "agreement 0.85 is below the agreed 0.9"
        )

    def test_no_unsupported_bar_gates_on_the_agreement_alone(self):
        """Row 6, counter-example: no unsupported bar, exactly as before (R7.5).

        0 of 8 caught, and reported: nobody agreed a bar for that half, and a bar
        nobody agreed is one `dossier` may not invent.
        """
        calibration = _measured(0.95, unsupported=Tally(agreed=0, cases=8))

        assert _withheld(calibration, threshold=0.60, unsupported=None) is None

    def test_the_cli_gate_reads_the_bar_and_names_the_state(self, tmp_path: Path):
        """Row 2, at the command: the gate hands the declared bar to the decision.

        A `per_part` pipeline whose described judge measured 90% against its
        0.90 bar, catching 6 of 8 unsupported cases, under a described bar of
        0.875: withheld, naming the state, as R7.23 names it.
        """
        path = write_pipeline(
            tmp_path, modes={"extract": "per_part"}, inputs={"extract": "documents@page_images"}
        )
        path.write_text(
            path.read_text(encoding="utf-8") + "gold: gold/incidents/\n", encoding="utf-8"
        )
        gold = tmp_path / "gold" / "incidents"
        shutil.copytree(FIXTURE_GOLD, gold, dirs_exist_ok=True)
        (gold / "judge.yaml").write_text(
            f"root_cause:\n  {GROUNDED}: 0.95\n"
            f"  {DESCRIBED}: {{agreement: 0.90, unsupported: 0.875}}\n",
            encoding="utf-8",
        )
        rubric = path.parent / "rubrics" / "root_cause.md"
        for state, agreement, caught in ((GROUNDED, 1.0, 8), (DESCRIBED, 0.90, 6)):
            measured = gold / CALIBRATIONS_DIR / f"{judge_name('root_cause', state)}.json"
            measured.parent.mkdir(parents=True, exist_ok=True)
            measured.write_text(
                json.dumps(
                    {
                        "judge_model": "anthropic:claude-sonnet-4-5-20250929",
                        "rubric_hash": text_hash(rubric),
                        "prompt_hash": judge_prompt_hash(),
                        "agreement": agreement,
                        "sample_size": 20,
                        "lower_bound": 0.7,
                        "kappa": 0.8,
                        "supported": {"agreed": 12, "cases": 12},
                        "unsupported": {"agreed": caught, "cases": 8},
                    }
                ),
                encoding="utf-8",
            )
        config = load_pipeline(path, providers=PROVIDERS)

        _, withheld = judge_gate(
            gold,
            path.parent / "schemas" / "incident.yaml",
            path.parent,
            "anthropic:claude-sonnet-4-5-20250929",
            states=judged_states(per_part=True),
        )

        assert config.gold is not None
        assert withheld == {
            "root_cause": "described: unsupported 6 of 8 (75.0%) is below the agreed 87.5%"
        }
