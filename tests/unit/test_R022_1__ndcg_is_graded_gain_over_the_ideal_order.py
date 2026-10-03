"""R22.1 — a query's nDCG@10 is the graded gain of the documents listed,
discounted by rank, over the best order its judgments allow.

Gain `2^grade - 1`, discount `log2(rank + 1)`, the rank counted from 1; the
ideal is the judged documents by grade, the first ten. An unjudged document
gains nothing. A grade 2 counts three times a grade 1, which is what makes
"answers it" and "related" different.
"""

from __future__ import annotations

import pytest

from dossier.domain.relevance import ndcg_at

INC_4830 = "incidents-jira:INC-4830"
INC_4821 = "incidents-jira:INC-4821"
UNJUDGED = [f"incidents-jira:INC-90{n:02d}" for n in range(20)]


class TestNdcgIsGradedGainOverTheIdealOrder:
    """R22.1 — the order listed, against the best order the judgments allow."""

    def test_the_answer_listed_first_is_the_best_order(self):
        """Row 1 — the one where the answer is first."""
        assert ndcg_at([INC_4830, *UNJUDGED[:9]], {INC_4830: 2}) == pytest.approx(1.0)

    def test_the_answer_behind_two_unjudged_documents(self):
        """Row 2 — the one listed third: `3 / log2(4)` over `3`."""
        listed = [UNJUDGED[0], UNJUDGED[1], INC_4830]

        assert round(ndcg_at(listed, {INC_4830: 2}), 3) == 0.5

    def test_two_grades_in_the_wrong_order(self):
        """Row 3 — the related one first: `1 + 3 / log2(3)` over `3 + 1 / log2(3)`."""
        judged = {INC_4830: 2, INC_4821: 1}

        assert round(ndcg_at([INC_4821, INC_4830], judged), 3) == 0.797

    def test_the_answer_past_the_first_ten_gains_nothing(self):
        """Row 4, counter-example — the one listed eleventh."""
        listed = [*UNJUDGED[:10], INC_4830]

        assert ndcg_at(listed, {INC_4830: 2}) == 0.0
