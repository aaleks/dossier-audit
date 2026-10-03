"""R22.4 — a query with no document graded 1 or 2 is named and left out of
the means.

Its nDCG has no ideal to divide by, and averaging it in as 0 would lower the
mean for a question nobody judged answerable.
"""

from __future__ import annotations

from dossier.domain.relevance import Measured, means, measured

INC_4830 = "incidents-jira:INC-4830"
INC_4821 = "incidents-jira:INC-4821"
UNJUDGED = [f"incidents-jira:INC-90{n:02d}" for n in range(20)]


ANSWERED = "certificate-expired-at-checkout"
UNANSWERABLE = "alert-routed-to-an-archived-channel"


class TestAQueryWithNothingRelevantIsLeftOutOfTheMeans:
    """R22.4 — named, not averaged in as 0."""

    def test_a_query_nothing_answers_is_named_and_not_averaged(self):
        """Row 1 — the one whose second query has every judgment 0."""
        first = measured(ANSWERED, [INC_4830], {INC_4830: 2})
        second = measured(UNANSWERABLE, [INC_4821], {INC_4821: 0})

        assert second == Measured(name=UNANSWERABLE, ndcg=None, recall=None, unjudged=0)
        found = means([first, second])
        assert found.unscored == (UNANSWERABLE,)
        assert (found.ndcg, found.recall, found.scored) == (1.0, 1.0, 1)

    def test_a_query_with_one_related_document_is_averaged(self):
        """Row 2, counter-example — the one with a 1 the search did not list."""
        first = measured(ANSWERED, [INC_4830], {INC_4830: 2})
        second = measured(UNANSWERABLE, [UNJUDGED[0]], {INC_4821: 1})

        found = means([first, second])

        assert found.unscored == ()
        assert (found.ndcg, found.recall, found.scored) == (0.5, 0.5, 2)
