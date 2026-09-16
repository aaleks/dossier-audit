"""R2.7 — an item leaving scope is tombstoned, and its snapshots stay resolvable.

A run from March must still resolve the documents it used.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.sync import State, tombstones

HELD = {"INC-4821", "INC-4822", "audit-note.pdf"}


class TestTombstones:
    """R2.7 — leaving scope is a state change, never a deletion."""

    def test_an_item_absent_from_a_full_listing_is_tombstoned(self):
        """Example 1: the one where `INC-4821` drops out of the query."""
        assert tombstones(held=HELD, listed={"INC-4822", "audit-note.pdf"}) == ("INC-4821",)

    def test_an_item_still_listed_is_left_alone(self):
        """The one where nothing left, so nothing is marked."""
        assert tombstones(held=HELD, listed=HELD) == ()

    def test_an_item_new_to_the_listing_is_not_a_tombstone(self):
        """The one where arrival is not departure.

        `INC-4901` appearing for the first time is R2.1's business, not this
        rule's. Returning it here would tombstone an item on the sync that
        introduced it.
        """
        assert tombstones(held=HELD, listed=HELD | {"INC-4901"}) == ()

    def test_an_already_tombstoned_item_is_not_returned_again(self):
        """The one where re-tombstoning would rewrite history.

        `first_seen` and the original transition are recorded once. An item that
        left scope two syncs ago has not left it again.
        """
        assert tombstones(held={"INC-4822"}, listed=set(), already_tombstoned={"INC-4821"}) == (
            "INC-4822",
        )

    def test_an_item_returning_to_scope_is_not_tombstoned(self):
        """Example 3: the one where `INC-4821` comes back.

        Reactivation is the ledger's job; what matters here is that a returning
        item is not in the set of departures.
        """
        assert (
            tombstones(
                held={"INC-4822"},
                listed={"INC-4821", "INC-4822"},
                already_tombstoned={"INC-4821"},
            )
            == ()
        )

    def test_reactivated_names_the_items_that_came_back(self):
        """The other half of the same sync, so the caller cannot forget it.

        An item that returns must go back to `active`, and a function that only
        reported departures would leave the ledger permanently wrong about it.
        """
        from dossier.domain.sync import reactivated

        assert reactivated(
            listed={"INC-4821", "INC-4822"}, already_tombstoned={"INC-4821"}
        ) == ("INC-4821",)

    def test_an_empty_listing_tombstones_everything_held(self):
        """The boundary: the one where the whole source went away.

        Deliberately allowed. A source pointed at the wrong place will tombstone
        its whole contents -- and because nothing is deleted, that is recoverable
        by fixing the configuration and syncing again.
        """
        assert tombstones(held=HELD, listed=set()) == tuple(sorted(HELD))

    def test_an_incremental_listing_must_not_be_used(self):
        """Counter-example (row 4): the one where `since` was set.

        Tombstoning is computed only against a full listing (R1.3). Handing this
        function an incremental one would mark every unchanged item as gone --
        the single most destructive thing sync could do, and it would look like
        it worked.
        """
        with pytest.raises(ValueError):
            tombstones(held=HELD, listed={"INC-4822"}, listing_was_complete=False)


class TestState:
    """The two states a ledger row can be in (spec 002)."""

    def test_the_states_are_active_and_tombstoned(self):
        assert {state.value for state in State} == {"active", "tombstoned"}
