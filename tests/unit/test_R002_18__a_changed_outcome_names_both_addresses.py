"""R2.18 — a changed item is named with the address it held and the one it holds now.

The decision, apart from the sync that acts on it: given what `classify` said
about an item and where its bytes were and are, is there something to name, and
what does the line say? Only a `CHANGED` outcome names anything. A new item has
no previous address, and an unchanged one has nothing to say beyond the count
(R2.18 rows 4 and 5).

The addresses are snapshot addresses -- the raw payload's own hash, which is the
last segment of the row's `snapshot_path` (R2.11) -- never the normalised
`content_hash`, which for a source declaring `fields` addresses nothing stored
(R2.17).
"""

from __future__ import annotations

import pytest

from dossier.domain.store import held_address, snapshot_path
from dossier.domain.sync import Change, Repointed, repointed

# `INC-4822` before and after the edit R2.2 row 3 describes, as full digests.
BEFORE = "0e52dd18" + "0" * 56
AFTER = "77c1b40a" + "0" * 56


class TestAChangedOutcomeNamesBothAddresses:
    """R2.18 — a changed item is named with the address it held and the one it holds now."""

    def test_a_changed_item_names_the_address_it_held_and_the_one_it_holds_now(self):
        """Example 1: the one where `INC-4822` moved from `0e52dd18` to `77c1b40a`."""
        named = repointed(
            key="INC-4822",
            outcome=Change.CHANGED,
            previous=snapshot_path(BEFORE),
            stored=AFTER,
        )

        assert named == Repointed(key="INC-4822", held=BEFORE, now=AFTER)

    @pytest.mark.parametrize(
        ("outcome", "previous"),
        [
            pytest.param(Change.UNCHANGED, snapshot_path(BEFORE), id="unchanged"),
            pytest.param(Change.NEW, None, id="new"),
        ],
    )
    def test_an_unchanged_or_new_item_names_nothing(
        self, outcome: Change, previous: str | None
    ):
        """Counter-examples (rows 4 and 5): the one re-read to the same hash, and the one
        seen for the first time.

        Neither has two addresses to show: the count already says everything the
        line would.
        """
        assert (
            repointed(key="INC-4822", outcome=outcome, previous=previous, stored=AFTER) is None
        )

    def test_the_address_is_the_last_segment_of_the_snapshot_path(self):
        """The one where the path is unpicked back into the hash it was built from (R2.11)."""
        assert held_address(snapshot_path(BEFORE)) == BEFORE

    def test_a_path_that_is_not_a_snapshot_path_is_refused(self):
        """Counter-example: the one where the path ends in a display prefix.

        A prefix would print as a plausible address nobody can open (R0.7).
        """
        with pytest.raises(ValueError, match="content hash"):
            held_address("0e/52/0e52dd18")
