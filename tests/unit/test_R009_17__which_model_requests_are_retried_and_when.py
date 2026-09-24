"""R9.17 — a model request answered 408, 409, 429 or 5xx, or not answered at all,
is sent again up to twice before it fails.

The decisions, without a client or a server: which answers are worth the same
request again, and how long to wait before sending it. Both are pure, so the
jitter and the clock arrive as arguments and every row is an exact assertion.
The list and the numbers are both official SDKs', value for value.
"""

from __future__ import annotations

import pytest

from dossier.domain.retries import retryable


class TestWhichAnswersAreSentAgain:
    """R9.17 — which answers are retried: rows 1, 3, 4, 5, 7 and 8."""

    @pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504, 529])
    def test_an_answer_the_server_may_not_give_again_is_retried(self, status: int):
        """Rows 1, 3 and 5: the one where the server is busy rather than refusing.

        529 is Anthropic's "overloaded", and a 5xx like any other: the policy is
        every provider's, not one client's.
        """
        assert retryable(status)

    def test_no_answer_at_all_is_retried(self):
        """Row 4: the one where no server answered -- refused, reset or timed out."""
        assert retryable(None)

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_an_answer_that_would_come_back_the_same_is_not(self, status: int):
        """Rows 7 and 8, counter-examples: the one where asking again changes nothing.

        A key refused once is refused again, and a request the server could not
        read is not re-read. Sending either twice only doubles the refusal.
        """
        assert not retryable(status)
