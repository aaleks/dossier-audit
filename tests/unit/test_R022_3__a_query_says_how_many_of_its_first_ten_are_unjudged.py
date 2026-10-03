"""R22.3 — each query says how many of the documents in its first ten no
judgment names.

An unjudged document counts as not relevant, so a high count means the score
says little yet: the holes in the gold, said rather than hidden.
"""

from __future__ import annotations

from dossier.domain.relevance import unjudged

INC_4830 = "incidents-jira:INC-4830"
INC_4821 = "incidents-jira:INC-4821"
UNJUDGED = [f"incidents-jira:INC-90{n:02d}" for n in range(20)]


class TestAQuerySaysHowManyOfItsFirstTenAreUnjudged:
    """R22.3 — counted in the first ten, as the measures are."""

    def test_three_of_ten_unjudged(self):
        """Row 1 — the one with three holes."""
        judged = {doc: 0 for doc in UNJUDGED[3:10]}

        assert unjudged(UNJUDGED[:10], judged) == 3

    def test_a_0_is_a_judgment(self):
        """Row 2, counter-example — the one judged throughout, one of them 0."""
        listed = [INC_4830, INC_4821]

        assert unjudged(listed, {INC_4830: 2, INC_4821: 0}) == 0

    def test_only_the_first_ten_are_counted(self):
        """The cut — an unjudged eleventh is past what the measures read."""
        listed = UNJUDGED[:11]
        judged = {doc: 0 for doc in UNJUDGED[:10]}

        assert unjudged(listed, judged) == 0
