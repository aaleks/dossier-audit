"""R7.12 — the judge marks a planted unsupported claim as unsupported.

The single case that distinguishes a working judge from one that agrees with
everything. A judge that passes every input is indistinguishable from no judge,
and it would score 60% on the calibration sample without reading a word of it --
twelve of the twenty cases are supported.

`rc-02` is that case: the quarter-end change freeze, which `INC-4830` mentions
only as a contributing factor that added thirteen minutes to recovery, offered as
the cause of the outage. Plausible, adjacent to the truth, and stated nowhere in
the document.

A real model call, so this is `live`:

    uv run python -m pytest tests/evals -m live -s
"""

from __future__ import annotations

import json

import pytest
from tests.evals.test_R007_11__judge_agrees_with_human_scores import (
    CASES,
    JUDGE_MODEL,
    RUBRIC,
    document_text,
    judge,
)

from dossier.application.eval import judged

pytestmark = pytest.mark.live

PLANTED = "rc-02"


def planted_case() -> dict:
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = json.loads(line)
            if case["id"] == PLANTED:
                return case
    raise AssertionError(f"{PLANTED} is not in the calibration sample")


class TestJudgeDetectsAPlantedUnsupportedClaim:
    """R7.12 — a cause the document does not state is not supported."""

    def test_the_planted_claim_is_marked_unsupported(self):
        """Example 1: the one naming a cause absent from the document.

        The boolean only (row 2). What the judge says about *why* is useful to a
        person reading a calibration report and is not a claim any rule makes:
        asserting its wording would break on a model that reasons identically
        and phrases it differently.
        """
        case = planted_case()
        assert case["supported"] is False, "the sample's planted case must be unsupported"

        supported, evidence = judged(
            judge(),
            rubric=(RUBRIC / "root_cause.md").read_text(encoding="utf-8"),
            document=case["document"],
            text=document_text(case),
            answer=case["answer"],
        )

        print(f"\n  judge:    {JUDGE_MODEL}")
        print(f"  verdict:  supported={supported}")
        print(f"  evidence: {evidence[:300]}")

        assert supported is False, (
            f"{JUDGE_MODEL} called a planted unsupported claim supported. "
            "A judge that agrees with everything is indistinguishable from no judge."
        )
