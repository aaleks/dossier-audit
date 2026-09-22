"""R11.14 — an eval and a comparison attach the per-document detail they printed.

An eval prints one line per miss and records a percentage. The percentage says a
field is at 75.0%; the lines say which document and why, which is the difference
between knowing a field is weak and knowing what to do about it. They lived only
in the terminal: R0.11's run directory does not hold them, because a score is not
something a run produced.

Composed from what was printed, as `changes.json` is (R11.6), and sorted, so the
bytes do not depend on the order anything happened to run in (R0.4).
"""

from __future__ import annotations

import json

from dossier.application.eval import deltas_artifact, scores_artifact
from dossier.domain.scoring import (
    DocumentScore,
    FieldDelta,
    FieldScore,
    FieldTotal,
    Verdict,
)

# The scoring example's four disagreements (R7.2), with the details the report
# prints beside them.
SCORES = (
    DocumentScore(
        document="INC-4821",
        results=(FieldScore(field="loss_amount", verdict=Verdict.CORRECT),),
    ),
    DocumentScore(
        document="INC-4901",
        results=(
            FieldScore(
                field="resolution_date",
                verdict=Verdict.INCORRECT,
                detail="'2026-08-12' does not match '2026-08-11'",
            ),
        ),
    ),
    DocumentScore(
        document="INC-4822",
        results=(
            FieldScore(
                field="root_cause",
                verdict=Verdict.INCORRECT,
                detail="answered 'disk pressure on the batch host'; gold abstains",
                judged=True,
            ),
        ),
    ),
)


class TestAnEvalAttachesTheDetailItPrinted:
    """R11.14 — an eval and a comparison attach the detail they printed."""

    def test_every_scored_field_of_every_document_is_an_entry(self):
        """Example 1: the one where the terminal has scrolled away."""
        entries = json.loads(scores_artifact(SCORES, withheld={}))["scores"]

        assert len(entries) == 3
        assert {entry["document"] for entry in entries} == {
            "INC-4821",
            "INC-4822",
            "INC-4901",
        }

    def test_a_miss_carries_the_words_the_report_printed(self):
        """Example 2: the one where the reason is the point.

        `gold abstains` and `does not match` send a reader to two different
        places. A boolean would send them to neither (R7.4 row 2).
        """
        entries = {
            entry["document"]: entry
            for entry in json.loads(scores_artifact(SCORES, withheld={}))["scores"]
        }

        assert entries["INC-4822"]["verdict"] == "incorrect"
        assert "gold abstains" in entries["INC-4822"]["detail"]
        assert entries["INC-4822"]["judged"] is True
        assert entries["INC-4821"]["verdict"] == "correct"

    def test_a_withheld_field_is_named_with_its_reason_and_no_verdict(self):
        """Counter-example (row 5): the one whose judge may not be quoted (R7.15).

        Named, never omitted. A field that simply vanished from the artifact
        would read as one nobody verified, which is a different problem wanting
        different work (R7.3 row 4).
        """
        held = json.loads(scores_artifact(SCORES, withheld={"root_cause": "calibration stale"}))

        assert held["withheld"] == {"root_cause": "calibration stale"}

    def test_the_bytes_do_not_depend_on_the_order_the_documents_ran_in(self):
        """The determinism boundary (R0.4), on an artifact that enters no key.

        Nothing here reaches a cache key (R10.4), so nothing would break -- and
        two evals of one run producing different bytes is exactly the kind of
        difference someone would spend an afternoon explaining.
        """
        assert scores_artifact(SCORES, withheld={}) == scores_artifact(
            tuple(reversed(SCORES)), withheld={}
        )

    def test_a_comparison_attaches_the_table_it_printed(self):
        """Example 3: the one a person reads a month later.

        The same three columns the terminal prints, and the regression marked
        where the terminal marks it.
        """
        rows = (
            FieldDelta(
                field="affected_systems",
                before=FieldTotal(field="affected_systems", correct=3, scored=4),
                after=FieldTotal(field="affected_systems", correct=2, scored=4),
            ),
        )

        table = deltas_artifact(rows, runs=("20260806T142203Z-4f1a", "20260907T090000Z-bbbb"))

        assert "affected_systems" in table.decode("utf-8")
        assert "75.0%" in table.decode("utf-8")
        assert "50.0%" in table.decode("utf-8")
        assert "-25.0" in table.decode("utf-8")
        assert "regression" in table.decode("utf-8")
