"""R7.35 — `--compare` refuses two runs shown different reference documents, by
key or by snapshot. The decision.

Two resolved plans in: the check reads which reference documents each run
pinned, and whether any of its steps reads `reference` at all. A field can move
because its procedure did, and a delta would credit the configuration with it
(R7.8's reason, one level out). By snapshot, because a procedure tightened in
place keeps its key.
"""

from __future__ import annotations

import pytest

from dossier.domain.resolution import PinnedDocument, ResolvedPlan, ResolvedStep
from dossier.domain.scoring import check_same_reference

RUNS = ("20260806T142203Z-4f1a", "20260907T090000Z-bbbb")
SNAPSHOT = "b81f0c6d" * 8
NEW_SNAPSHOT = "5b1e77a4" * 8
VERIFY = ["documents", "extract", "reference"]


def _plan(*, reference: dict[str, str], verify: list[str] = VERIFY) -> ResolvedPlan:
    """`extract` then `verify`, over `INC-4821`, with `reference` pinned as given."""
    return ResolvedPlan(
        pipeline="incident-audit",
        pipeline_hash="b81f0c6d" * 8,
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            ResolvedStep(id="extract", inputs=["documents"], prompt_hash="0e52dd18" * 8),
            ResolvedStep(id="verify", inputs=verify, prompt_hash="0e52dd18" * 8),
        ],
        documents=[PinnedDocument(key="INC-4821", snapshot="a3f9c1e2" * 8)],
        reference=[
            PinnedDocument(key=key, snapshot=snapshot) for key, snapshot in reference.items()
        ],
    )


class TestCompareRefusesRunsShownDifferentReference:
    """R7.35 — two runs compare only if their calls were shown the same context."""

    def test_a_procedure_tightened_in_place_is_refused(self):
        """Row 1: the one where `OPS-114` kept its key and changed its words."""
        with pytest.raises(ValueError) as refused:
            check_same_reference(
                _plan(reference={"OPS-114": SNAPSHOT}),
                _plan(reference={"OPS-114": NEW_SNAPSHOT}),
                runs=RUNS,
            )

        assert str(refused.value) == (
            f"runs {RUNS[0]} and {RUNS[1]} were shown different reference documents -- "
            "OPS-114 changed. A field can move because its context did."
        )

    def test_a_procedure_only_one_run_was_shown_is_refused(self):
        """Row 2: the one where run `b` was shown `OPS-116` as well."""
        with pytest.raises(ValueError, match=f"only in {RUNS[1]}: OPS-116"):
            check_same_reference(
                _plan(reference={"OPS-114": SNAPSHOT}),
                _plan(reference={"OPS-114": SNAPSHOT, "OPS-116": SNAPSHOT}),
                runs=RUNS,
            )

    def test_the_same_procedures_at_the_same_snapshots_compare(self):
        """Row 3: counter-example -- the one where only the prompt was edited."""
        check_same_reference(
            _plan(reference={"OPS-114": SNAPSHOT, "OPS-116": SNAPSHOT}),
            _plan(reference={"OPS-114": SNAPSHOT, "OPS-116": SNAPSHOT}),
            runs=RUNS,
        )

    def test_a_pipeline_with_no_reference_compares(self):
        """Row 4: counter-example -- nothing to differ."""
        check_same_reference(_plan(reference={}), _plan(reference={}), runs=RUNS)

    def test_a_procedure_no_step_reads_does_not_stop_a_comparison(self):
        """Row 5: counter-example -- `reference:` declared, and no step reads it.

        `OPS-114` moved, and no call of either run was shown it, so it cannot
        have moved a field.
        """
        check_same_reference(
            _plan(reference={"OPS-114": SNAPSHOT}, verify=["documents", "extract"]),
            _plan(reference={"OPS-114": NEW_SNAPSHOT}, verify=["documents", "extract"]),
            runs=RUNS,
        )
