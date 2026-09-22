"""R11.17 - what each command's record says about itself.

The acceptance test beside this one proves the four commands actually attach a
description, and that what it says is what the terminal said. This one proves the
composition: which header each kind carries, and that the lines under it are the
command's own, verbatim.

`lines` is what the command printed, handed over rather than recomposed. That is
the whole design: a description built from a second format string would be a
second way of arriving at a figure, which is what spec 011 forbids, and the
indentation is the only thing removed.
"""

from __future__ import annotations

from dossier.domain.judges import Calibration
from dossier.domain.tracking import (
    calibration_description,
    convert_description,
    judge_line,
    run_description,
    step_line,
    sync_description,
)

RUN = "20260806T142203Z-4f1a"
PIPELINE = "incident-audit"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
PIPELINE_HASH = "2f60a7d3" + "0" * 56
GOLD_HASH = "3b7e1d90" + "0" * 56


class TestStepLine:
    """The line `dossier run` prints per step, composed once for both readers."""

    def test_a_step_names_its_documents_its_cache_hits_and_its_failures(self):
        """The one where a step ran cleanly: three numbers and nothing else."""
        assert (
            step_line(step="verify", documents=4, cached=4, failed=0)
            == "verify: 4 document(s) · 4 from cache · 0 failed"
        )

    def test_described_and_findings_appear_only_when_there_are_any(self):
        """The one where the two optional counts are present.

        Absent when zero, for the reason R6.15 gives: `· 0 described` on every
        line of every run of every text pipeline is noise, and the number is
        interesting precisely because it is usually absent.
        """
        assert (
            step_line(step="extract", documents=4, cached=0, failed=1, described=2, findings=3)
            == "extract: 4 document(s) · 0 from cache · 1 failed · 2 described · 3 finding(s)"
        )


class TestJudgeLine:
    """The line `dossier calibrate` prints per judged field (R7.14)."""

    def test_a_measurement_names_its_field_its_agreement_and_its_judge(self):
        """The one from R11.5 row 1: twenty cases, full agreement."""
        assert judge_line(
            field="root_cause", agreement=1.0, cases=20, judge_model="openai:gpt-5.4-mini"
        ).strip() == ("root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini")

    def test_one_case_is_a_case_not_cases(self):
        """The one where the plural would be wrong. A sample of one is refused
        by R7.14 row 3, so this never reaches a record -- but the line is shared
        with the terminal, and the terminal prints what it is given."""
        assert "over 1 case ·" in judge_line(
            field="root_cause", agreement=0.0, cases=1, judge_model="openai:gpt-5.4-mini"
        )


class TestEachCommandDescribesItself:
    """R11.17 - the header per kind, and the command's own lines beneath it."""

    def test_a_run_says_its_id_its_model_and_what_each_step_did(self):
        """Example 1: the one where the record says more than its title does.

        The pipeline hash is shown at the display width every other record uses
        (R10.10), because a 64-character hash in a description pushes the lines
        that matter off the card.
        """
        assert run_description(
            run_id=RUN,
            pipeline=PIPELINE,
            model=MODEL,
            pipeline_hash=PIPELINE_HASH,
            lines=["  extract: 4 document(s) · 0 from cache · 0 failed"],
        ) == (
            f"run {RUN} · {PIPELINE}\n"
            f"model {MODEL} · pipeline 2f60a7d3\n"
            "extract: 4 document(s) · 0 from cache · 0 failed"
        )

    def test_a_sync_says_its_pipeline_and_the_lines_it_printed(self):
        """Example 3: the source's counts and what the ledger did with them."""
        assert sync_description(
            pipeline=PIPELINE,
            lines=[
                "incidents-jira  420 known · 18 changed · 2 new -> 20 fetched",
                "ledger updated · 20 new snapshots · 0 tombstoned",
            ],
        ) == (
            f"sync {PIPELINE}\n"
            "incidents-jira  420 known · 18 changed · 2 new -> 20 fetched\n"
            "ledger updated · 20 new snapshots · 0 tombstoned"
        )

    def test_a_convert_says_what_it_held_converted_and_served(self):
        """Example 4: the counts R8.8 prints, under the convert header."""
        assert convert_description(
            pipeline=PIPELINE,
            lines=[
                "incidents-manual  3 held · 3 converted · 0 cached",
                "cache updated · 3 converted · 0 cached",
            ],
        ) == (
            f"convert {PIPELINE}\n"
            "incidents-manual  3 held · 3 converted · 0 cached\n"
            "cache updated · 3 converted · 0 cached"
        )

    def test_a_calibration_says_which_gold_set_it_measured_against(self):
        """Example 5: the gold set by name and hash, then the measurement.

        The gold set is on the header and not in the line, because the line is
        per field and the gold set is per run -- and because a second
        calibration of the same field against edited answers is a different
        measurement that would otherwise look identical (R7.14 row 2).
        """
        assert calibration_description(
            pipeline=PIPELINE,
            gold="gold/incidents",
            gold_hash=GOLD_HASH,
            lines=["root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini"],
        ) == (
            f"calibrate {PIPELINE} · gold incidents 3b7e1d90\n"
            "root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini"
        )

    def test_a_command_that_printed_nothing_describes_only_itself(self):
        """Counter-example: the one where there is nothing to restate.

        A blank line is dropped rather than carried: MLflow renders the
        description as markdown, and a trailing blank reads as a paragraph
        break before nothing.
        """
        assert sync_description(pipeline=PIPELINE, lines=["", "   "]) == f"sync {PIPELINE}"

    def test_the_lines_are_the_command_s_own_words(self):
        """Counter-example: the one where the caller's text is not reformatted.

        Whatever the command printed is what the record holds. A description
        that rephrased it could disagree with the terminal, which is the
        disagreement spec 011 exists to rule out.
        """
        odd = "incidents-jira  0 known · 0 changed · 0 new -> 0 fetched"
        assert odd in sync_description(pipeline=PIPELINE, lines=[odd])


class TestJudgeLineFromACalibration:
    """The measurement a calibration holds, as the terminal prints it."""

    def test_a_calibration_renders_the_line_its_figures_make(self):
        """The one where the file, the terminal and the record cannot disagree."""
        measured = Calibration(
            judge_model="openai:gpt-5.4-mini",
            rubric_hash="f7a2d9c4" + "0" * 56,
            prompt_hash="0" * 64,
            agreement=1.0,
            sample_size=20,
        )
        assert judge_line(
            field="root_cause",
            agreement=measured.agreement,
            cases=measured.sample_size,
            judge_model=measured.judge_model,
        ).strip() == ("root_cause         100.0% agreement over 20 cases · openai:gpt-5.4-mini")
