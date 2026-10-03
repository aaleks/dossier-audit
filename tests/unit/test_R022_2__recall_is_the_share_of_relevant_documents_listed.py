"""R22.2 — a query's recall@10 is the share of the documents graded 1 or 2
that the search lists in its first ten.
"""

from __future__ import annotations

from dossier.domain.relevance import recall_at

INC_4830 = "incidents-jira:INC-4830"
INC_4821 = "incidents-jira:INC-4821"
UNJUDGED = [f"incidents-jira:INC-90{n:02d}" for n in range(20)]


class TestRecallIsTheShareOfRelevantDocumentsListed:
    """R22.2 — of what a person judged worth finding, how much was found."""

    def test_one_of_two_relevant_documents_listed(self):
        """Row 1 — the one finding the answer and missing the related one."""
        judged = {INC_4830: 2, INC_4821: 1}

        assert recall_at([INC_4830, *UNJUDGED[:9], INC_4821], judged) == 0.5

    def test_a_document_graded_0_is_nothing_to_find(self):
        """Row 2, counter-example — the one with a 0 listed first."""
        judged = {INC_4821: 0, INC_4830: 2}

        assert recall_at([INC_4821, INC_4830], judged) == 1.0
