"""R2.4 — sync asks from `last_sync_at` minus an overlap, never from `last_sync_at`.

Clock skew between dossier and the source, plus source-side indexing lag, will
otherwise drop items silently. The default overlap is 24 hours, configurable per
source.

The rows below are the rule's example table, transcribed. Values come from
`specs/_fixtures.md`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dossier.domain.sync import DEFAULT_OVERLAP, window_start

LAST_SYNC = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)
ONE_DAY_EARLIER = datetime(2026, 8, 5, 9, 0, 0, tzinfo=UTC)
TWO_DAYS_EARLIER = datetime(2026, 8, 4, 9, 0, 0, tzinfo=UTC)

# INC-4822 changed at this time but was not yet indexed when the previous sync ran.
LATE_INDEXED_CHANGE = datetime(2026, 8, 5, 16, 2, 0, tzinfo=UTC)


class TestWindowStart:
    """R2.4 — the window opens before the watermark, not at it."""

    def test_the_default_overlap_pulls_the_window_back_a_day(self):
        """The one where the overlap does its job.

        Example 1.
        """
        assert window_start(LAST_SYNC, overlap=DEFAULT_OVERLAP) == ONE_DAY_EARLIER

    def test_the_default_overlap_is_twenty_four_hours(self):
        """The one where the documented default is the actual default.

        The spec states 24 hours in prose. A default nobody asserts is a default
        that drifts.
        """
        assert DEFAULT_OVERLAP.total_seconds() == 24 * 60 * 60

    def test_a_longer_overlap_reaches_further_back(self):
        """Example 2: the one where a source configures 48h.

        Not a duplicate of example 1 with a different number: this is what proves
        the overlap is read at all rather than subtracted as a constant.
        """
        assert window_start(LAST_SYNC, overlap=timedelta(hours=48)) == TWO_DAYS_EARLIER

    def test_a_late_indexed_item_falls_inside_the_window(self):
        """Example 3: the one the rule exists for.

        `INC-4822` changed at 16:02 the day before the watermark but was not
        visible to the previous sync. Asking from the watermark itself would skip
        it forever -- it is old news by the time anyone looks.
        """
        since = window_start(LAST_SYNC, overlap=DEFAULT_OVERLAP)

        assert since < LATE_INDEXED_CHANGE < LAST_SYNC

    def test_a_source_that_has_never_synced_asks_for_everything(self):
        """Counter-example (row 4): the one where there is no watermark.

        `since = None` means a full listing, which is also what tombstoning is
        computed against (R1.3, R2.7).
        """
        assert window_start(None, overlap=DEFAULT_OVERLAP) is None

    def test_a_naive_timestamp_is_refused(self):
        """The one where a timezone-less watermark would silently shift the window.

        A naive datetime is interpreted differently depending on the machine that
        reads it, which is exactly the cross-machine variation R0.4 rules out. An
        hour of skew here is an item quietly not fetched.
        """
        with pytest.raises(ValueError):
            window_start(datetime(2026, 8, 6, 9, 0, 0), overlap=DEFAULT_OVERLAP)

    def test_a_negative_overlap_is_refused(self):
        """The one where the window would open after the watermark.

        That is the precise failure the rule forbids, expressed as configuration
        rather than as a bug: `watermark_overlap: -1h` must not quietly become a
        sync that skips its own boundary.
        """
        with pytest.raises(ValueError):
            window_start(LAST_SYNC, overlap=timedelta(hours=-1))

    def test_a_zero_overlap_is_refused(self):
        """The one exactly at the boundary the rule names.

        "never from `last_sync_at`" -- a zero overlap is asking from the
        watermark itself, which is the thing the rule rules out. The
        counter-example on a threshold rule is the off-by-one.
        """
        with pytest.raises(ValueError):
            window_start(LAST_SYNC, overlap=timedelta(0))


class _Recording:
    """A connector that lists nothing and remembers what it was asked for."""

    lists_everything = False

    def __init__(self) -> None:
        self.asked: list[datetime | None] = []

    def list(self, since: datetime | None = None):
        self.asked.append(since)
        return iter(())

    def fetch(self, key: str):
        raise AssertionError(f"nothing was listed, so {key!r} should not be fetched")

    def attachments(self, key: str):
        return iter(())


def _sync_once(tmp_path, connector: _Recording, overlap: timedelta | None) -> None:
    """One sync of `incidents-jira`, watermarked at `LAST_SYNC`, with `overlap` configured."""
    from dossier.application.sync import sync_source
    from dossier.domain.pipeline import SourceConfig
    from dossier.infrastructure.ledger import Ledger
    from dossier.infrastructure.store import SnapshotStore

    config = SourceConfig(id="incidents-jira", type="jira", watermark_overlap=overlap)
    with Ledger(tmp_path) as ledger:
        ledger.set_watermark("incidents-jira", LAST_SYNC)
        sync_source(
            config=config,
            connector=connector,
            store=SnapshotStore(tmp_path),
            ledger=ledger,
            now=datetime(2026, 8, 7, 9, 0, 0, tzinfo=UTC),
        )


class TestSyncAsksWithTheConfiguredOverlap:
    """R2.4 — "configurable per source": the overlap a source sets is the one sync uses."""

    def test_a_source_configuring_48h_is_asked_from_two_days_back(self, tmp_path):
        """Example 2, through sync: the one where the configured 48h reaches the connector.

        `window_start` has always honoured the overlap it is given. What was
        missing is that sync gave it the source's: a key the loader accepts and
        sync then ignores is configuration that lies about what will happen.
        """
        connector = _Recording()

        _sync_once(tmp_path, connector, timedelta(hours=48))

        assert connector.asked == [TWO_DAYS_EARLIER]

    def test_a_source_that_sets_no_overlap_gets_the_default(self, tmp_path):
        """Example 1, through sync: the one where nothing is configured and a day is used."""
        connector = _Recording()

        _sync_once(tmp_path, connector, None)

        assert connector.asked == [ONE_DAY_EARLIER]

    def test_a_configured_zero_is_refused_not_replaced_by_the_default(self, tmp_path):
        """The one where `watermark_overlap: 0h` is a mistake to report, not a gap to fill.

        Swapping it for the default would sync with an overlap nobody wrote.
        Passed through, `window_start` refuses it by name -- the zero boundary
        R2.4 draws -- before the connector is asked anything.
        """
        connector = _Recording()

        with pytest.raises(ValueError):
            _sync_once(tmp_path, connector, timedelta(0))

        assert connector.asked == []
