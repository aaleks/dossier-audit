"""R11.25 — a `dossier sync` records `<source>/returned` beside the other counts.

`known`, `changed` and `new` account for what `fetched` counts only with
`returned` beside them (R2.25). Without it the record reads as the terminal line
did before R2.25: `/fetched` 3 against `/known` 2, `/changed` 0 and `/new` 0.
The metric is recorded at zero too, as every count is (R11.4 row 3).

Which counts a sync records is a pure decision (`count_metrics`); the
acceptance test beside this one proves the command hands it the report's count.
"""

from __future__ import annotations

import pytest

from dossier.domain.tracking import count_metrics


class TestASyncCountsWhatCameBack:
    """R11.25 — `/returned`, beside `/known`, `/changed` and `/new`."""

    def test_the_revived_note_is_counted_under_its_source(self):
        """Row 1: the one where 2 known and 1 returned account for 3 fetched."""
        counts = {"known": 2, "changed": 0, "new": 0, "returned": 1, "fetched": 3, "failed": 0}

        assert count_metrics(kind="sync", source="incidents-manual", counts=counts) == {
            "incidents-manual/known": 2,
            "incidents-manual/changed": 0,
            "incidents-manual/new": 0,
            "incidents-manual/returned": 1,
            "incidents-manual/fetched": 3,
            "incidents-manual/failed": 0,
        }

    def test_an_item_back_with_other_bytes_is_returned_not_changed(self):
        """Row 2: the one where `INC-4821` changed while it was gone."""
        counts = {"known": 1, "changed": 0, "new": 0, "returned": 1, "fetched": 2, "failed": 0}

        recorded = count_metrics(kind="sync", source="incidents-jira", counts=counts)

        assert (recorded["incidents-jira/returned"], recorded["incidents-jira/changed"]) == (
            1,
            0,
        )

    def test_a_sync_where_nothing_came_back_records_a_zero(self):
        """Counter-example (row 3): the one recorded at zero rather than omitted."""
        counts = {"known": 3, "changed": 0, "new": 0, "returned": 0, "fetched": 3, "failed": 0}

        recorded = count_metrics(kind="sync", source="incidents-manual", counts=counts)

        assert recorded["incidents-manual/returned"] == 0

    def test_a_sync_that_does_not_say_what_came_back_is_refused(self):
        """The one where the caller forgot the count: refused, not recorded as absent."""
        counts = {"known": 3, "changed": 0, "new": 0, "fetched": 3, "failed": 0}

        with pytest.raises(ValueError, match="no returned count"):
            count_metrics(kind="sync", source="incidents-manual", counts=counts)
