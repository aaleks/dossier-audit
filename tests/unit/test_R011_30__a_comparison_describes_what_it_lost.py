"""R11.30 — a comparison's description says `regressed nothing` only when the
terminal marked nothing.

R11.12 has a comparison's description say what regressed, restating the
terminal's markers. R7.55 added a marker it did not read, so beside
`INC-4822 … <- regression` the description said `regressed nothing`. The
`regressed` line names each document the change lost after the fields, with the
step that failed it. Decided by `a.aleks` on 2026-09-30.

`failed` is what each run left unscored, as `(step, document, reason)` (R7.53).
"""

from __future__ import annotations

from pathlib import Path

from dossier.domain.scoring import FieldDelta, FieldTotal
from dossier.domain.tracking import comparison_description

RUN_ID = "20260806T142203Z-4f1a"
SECOND_RUN_ID = "20260907T090000Z-bbbb"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
GOLD_HASH = "3b7e1d90" + "0" * 56
REASON = "no valid output after 2 attempts"

# R7.54 row 1: over the three documents both runs answered, no field moved.
STILL = (
    FieldDelta(
        field="affected_systems",
        before=FieldTotal(field="affected_systems", correct=2, scored=3),
        after=FieldTotal(field="affected_systems", correct=2, scored=3),
    ),
)
# The comparison example (R7.8): `affected_systems` regresses.
WORSE = (
    FieldDelta(
        field="affected_systems",
        before=FieldTotal(field="affected_systems", correct=3, scored=4),
        after=FieldTotal(field="affected_systems", correct=2, scored=4),
    ),
)
FAILED_4822 = (("extract", "INC-4822", REASON),)


def _regressed(failed, *, rows=STILL) -> str:
    """The description's `regressed` line: its last."""
    described = comparison_description(
        runs=(RUN_ID, SECOND_RUN_ID),
        pipeline="incident-audit",
        models=(MODEL, MODEL),
        gold="incidents",
        gold_hash=GOLD_HASH,
        documents=4,
        rows=rows,
        overalls=(
            FieldTotal(field="overall", correct=12, scored=15),
            FieldTotal(field="overall", correct=12, scored=15),
        ),
        left_out=1,
        failed=failed,
    )
    return described.splitlines()[-1]


class TestAComparisonDescribesWhatItLost:
    """R11.30 — `regressed nothing` only when the terminal marked nothing."""

    def test_a_document_the_change_lost_is_named_as_regressed(self):
        """Row 1 — the one that said `regressed nothing` beside a marked document."""
        assert _regressed(((), FAILED_4822)) == "regressed INC-4822 (failed at extract)"

    def test_the_fields_come_first_as_the_terminal_prints_them(self):
        """Row 2 — the one where a field regressed too."""
        assert (
            _regressed(((), FAILED_4822), rows=WORSE)
            == "regressed affected_systems, INC-4822 (failed at extract)"
        )

    def test_a_document_the_change_recovered_is_not_a_regression(self):
        """Row 3, counter-example — the one where `a` failed it and `b` answered it."""
        assert _regressed((FAILED_4822, ())) == "regressed nothing"

    def test_a_document_both_runs_failed_is_not_a_regression(self):
        """Row 4, counter-example — the one where the change lost nothing."""
        assert _regressed((FAILED_4822, FAILED_4822)) == "regressed nothing"

    def test_the_command_describes_what_it_lost(self, workspace: Path, monkeypatch):
        """Row 1, through `dossier eval --compare`: R7.54 row 1's comparison, tracking on."""
        from tests.unit.test_R011_27__a_comparison_records_what_it_left_out import _recorded

        run, _ = _recorded(workspace, monkeypatch, failing="INC-4822")

        described = run.tags["mlflow.note.content"].splitlines()
        assert described[-1] == "regressed INC-4822 (failed at extract)", described
