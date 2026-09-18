"""R2.22 — `--full` asks every source for an unwindowed listing.

The same question the first sync asked, on demand: `since=None` whatever the
watermark says. The watermark itself is untouched by the asking -- it advances
afterwards as on any sync (R2.8 row 4), which the acceptance test proves.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dossier.domain.sync import sync_window

WATERMARK = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
DAY = timedelta(hours=24)


class TestAFullSyncStartsFromNothing:
    """R2.22 — the flag decides where the listing starts, and nothing else."""

    @pytest.mark.parametrize(
        ("full", "since"),
        [
            pytest.param(True, None, id="full-ignores-the-watermark"),
            pytest.param(
                False, datetime(2026, 8, 5, 9, 0, tzinfo=UTC), id="windowed-as-before"
            ),
        ],
    )
    def test_full_starts_from_nothing_whatever_the_watermark(self, full, since):
        """Row 1 and the counter-example: the one where the flag is the only difference."""
        assert (
            sync_window(reevaluating=False, last_sync_at=WATERMARK, overlap=DAY, full=full)
            == since
        )
