"""R11.5 — a `dossier calibrate` is one MLflow run per gold set holding what it
measured, with one trace per sample case.

The figures are the ones R7.14 writes to `calibrations/<field>.json` and the
terminal prints, so the file, the terminal and MLflow cannot disagree (spec
011). The decision of what a calibration records, and under which names, is
pure; recording it is the tracker port's, and the acceptance test beside this
one proves the command does.
"""

from __future__ import annotations

from dossier.domain.judges import Calibration

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUBRIC_HASH = "f7a2d9c4" * 8


def _record(calibration: Calibration, *, field: str = "root_cause"):
    """The params and metrics a calibration records for one judged field.

    Imported inside the helper: until this lands, collecting the default suite
    would error on a name that does not exist yet, and a red collection is not
    the same as a red test.
    """
    from dossier.domain.tracking import calibration_record

    return calibration_record(field=field, calibration=calibration)


class TestACalibrationRecordsOneRunWithOneTracePerCase:
    """R11.5 — the run holds what the file holds, under names MLflow can group."""

    def test_the_run_holds_the_figures_the_file_holds(self):
        """Example 1: the one where twenty of twenty is recorded as 100.0 over 20 cases.

        The model and the rubric hash are params -- what the figure was measured
        against -- and the agreement and the case count are metrics, so two runs
        under two judges sit side by side in MLflow's comparison. The agreement
        is the percentage the terminal prints, as accuracy is (spec 011).
        """
        measured = Calibration(
            judge_model=MODEL, rubric_hash=RUBRIC_HASH, agreement=1.0, sample_size=20
        )

        params, metrics = _record(measured)

        assert params == {
            "judge/root_cause/model": MODEL,
            "judge/root_cause/rubric": RUBRIC_HASH,
        }
        assert metrics == {"judge/root_cause/agreement": 100.0, "judge/root_cause/cases": 20}

    def test_a_case_trace_carries_the_document_and_both_verdicts(self):
        """Example 2: the one where the disagreeing case can be found.

        `INC-4830` is the planted case (R7.12): the reviewer marked its
        candidate unsupported, and here the judge marked it supported. Both
        verdicts are tags, so the cases the two disagree on are a filter on the
        experiment rather than a re-run.
        """
        from dossier.domain.tracking import case_tags

        assert case_tags(document="INC-4830", verified=False, judged=True) == {
            "dossier.document": "INC-4830",
            "dossier.verified": "unsupported",
            "dossier.judged": "supported",
        }
