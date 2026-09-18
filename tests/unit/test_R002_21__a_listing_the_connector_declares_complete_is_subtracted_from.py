"""R2.21 — tombstones are computed against any listing that is complete.

Complete for one of two reasons: sync asked for everything (`since=None`), or
the connector declares it returns everything whatever it is asked
(`lists_everything`, R1.11). Before this rule only the first counted.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dossier.domain.sync import listing_is_complete

WINDOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)


class TestAListingTheConnectorDeclaresCompleteIsSubtractedFrom:
    """R2.21 — the two ways a listing is complete, and the one way it is not."""

    @pytest.mark.parametrize(
        ("since", "lists_everything", "complete"),
        [
            pytest.param(WINDOW, True, True, id="folder-windowed-still-complete"),
            pytest.param(None, False, True, id="asked-for-everything"),
            pytest.param(None, True, True, id="both-reasons-at-once"),
            pytest.param(WINDOW, False, False, id="counter-example-jira-windowed"),
        ],
    )
    def test_a_listing_is_complete_for_either_reason(self, since, lists_everything, complete):
        """Rows 1, 2 and 4: the one where the folder is believed after its first sync,
        the one where nothing was subtracted, and the one where Jira legitimately
        omitted `INC-4821`.
        """
        assert listing_is_complete(since=since, lists_everything=lists_everything) is complete
