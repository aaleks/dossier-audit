"""R7.46 — a field a `per_part` step answers is one verdict per document,
however many of its pages answered it.

A field's percentage counts documents (R7.41). Counted per page, `INC-4830`'s
three pages would outvote a one-page document three to one on every field its
header carries. The values are `_fixtures.md`'s "`INC-4830` page by page".
"""

from __future__ import annotations

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import (
    FieldKind,
    GoldField,
    Verdict,
    per_field,
    score_document,
)

POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
CHART = "INC-5720-checkout-latency-postmortem.png"
GROUNDED = FieldCheck(FieldVerdict.VALID)
KINDS = {"severity": FieldKind.ENUM}


def answered(document: str, value: str) -> FieldRecord:
    return FieldRecord(
        field="severity", value=value, source=Evidence(document=document, span="SEV-1")
    )


def scored(document: str, values: list[str], gold: str):
    records = [answered(document, value) for value in values]
    return score_document(
        document=document,
        records=records,
        checks=[GROUNDED] * len(records),
        gold={"severity": GoldField(value=gold)},
        kinds=KINDS,
    )


class TestAPerPartFieldIsOneVerdictPerDocument:
    """R7.46 — one verdict for the document, not one for each page that answered."""

    def test_a_field_every_page_answers_is_one_of_one(self):
        """Row 1 — the one where the header repeats on every page."""
        score = scored(POSTMORTEM, ["critical", "critical", "critical"], "critical")

        assert [result.verdict for result in score.results] == [Verdict.CORRECT]
        (total,) = per_field([score], declared=["severity"])
        assert (total.correct, total.scored) == (1, 1)

    def test_a_long_document_weighs_what_a_one_page_one_does(self):
        """Row 2 — the one where three pages and one page are one document each."""
        scores = [
            scored(POSTMORTEM, ["critical", "critical", "critical"], "critical"),
            scored(CHART, ["major"], "major"),
        ]

        (total,) = per_field(scores, declared=["severity"])
        assert (total.correct, total.scored) == (2, 2)

    def test_a_per_file_answer_is_one_verdict_as_before(self):
        """Row 3, counter-example — the one with one answer and nothing to combine."""
        score = scored(CHART, ["major"], "major")

        assert [result.verdict for result in score.results] == [Verdict.CORRECT]
