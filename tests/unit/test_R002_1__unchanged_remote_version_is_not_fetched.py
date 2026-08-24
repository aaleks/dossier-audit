"""R2.1 — an item whose remote version is unchanged is not fetched.

Where the source offers a version marker, it is trusted and the payload is never
requested.

The rows below are the rule's example table, transcribed. Values come from
`specs/_fixtures.md`.
"""

from __future__ import annotations

import pytest

from dossier.domain.sync import needs_fetch


class TestRemoteVersionSkipsTheFetch:
    """R2.1 — trusting the server's marker is what makes sync cheap."""

    def test_an_unchanged_version_is_not_fetched(self):
        """The one where the server says nothing moved.

        Example 1: `OPS-114` at `v37`, still `v37`.
        """
        assert needs_fetch(recorded_version="v37", listed_version="v37") is False

    def test_a_changed_version_is_fetched(self):
        """Example 2: the one where the server says it moved."""
        assert needs_fetch(recorded_version="v37", listed_version="v38") is True

    def test_an_item_with_no_ledger_row_is_fetched(self):
        """Example 3: the one where `INC-4901` is new.

        An unknown item arrives with nothing recorded, so there is no marker to
        compare and it is always fetched.
        """
        assert needs_fetch(recorded_version=None, listed_version="2026-08-06T08:41:00Z") is True

    def test_a_source_with_no_version_marker_falls_through_to_hashing(self):
        """Counter-example (row 4): the one where the rule does not apply.

        `audit-note.pdf` comes from a folder, which has no version marker (R1.5).
        The rule cannot skip anything, so the payload is fetched and the decision
        passes to the content hash (R2.2). "Fetched" is not "stored".
        """
        assert needs_fetch(recorded_version=None, listed_version=None) is True

    def test_a_source_that_stops_reporting_a_version_is_fetched(self):
        """The one where the marker disappears.

        Recorded `v37`, now reported as nothing. The safe reading is that the
        source can no longer vouch for the item, so re-fetch and let the hash
        decide -- over-fetching is cheap, a missed change is not (R1.4).
        """
        assert needs_fetch(recorded_version="v37", listed_version=None) is True

    @pytest.mark.parametrize(
        ("recorded", "listed"),
        [
            pytest.param("v37", "V37", id="case"),
            pytest.param("v37", "v37 ", id="trailing-space"),
            pytest.param("2026-07-30T09:14:00Z", "2026-07-30T09:14:00z", id="tz-case"),
        ],
    )
    def test_version_markers_are_compared_exactly(self, recorded: str, listed: str):
        """The one where a near-match is treated as a change.

        A version marker is an opaque token from the source. Normalising it would
        mean guessing at another system's semantics, and guessing wrong here is a
        change that is never fetched.
        """
        assert needs_fetch(recorded_version=recorded, listed_version=listed) is True
