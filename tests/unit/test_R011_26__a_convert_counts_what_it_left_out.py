"""R11.26 — a `dossier convert` records `<source>/left_out` beside the other counts.

A document R8.27 leaves out is counted in `held` and printed as `· 1 left out`.
Without the metric, `/held` 3 against `/converted` 2, `/cached` 0 and `/failed`
0 leaves one document unaccounted for. The count is recorded at zero too, as
every count is (R11.4 row 3).

Which counts a convert records is a pure decision (`count_metrics`); the
acceptance test beside this one proves the command hands it the report's count.
"""

from __future__ import annotations

import pytest

from dossier.domain.tracking import count_metrics

SOURCE = "incidents-exports"


class TestAConvertCountsWhatItLeftOut:
    """R11.26 — `/left_out`, beside `/held`, `/converted`, `/cached` and `/failed`."""

    def test_the_json_left_out_is_counted_under_its_source(self):
        """Row 1: the one where 2 converted and 1 left out account for 3 held."""
        counts = {"held": 3, "converted": 2, "cached": 0, "failed": 0, "left_out": 1}

        assert count_metrics(kind="convert", source=SOURCE, counts=counts) == {
            f"{SOURCE}/held": 3,
            f"{SOURCE}/converted": 2,
            f"{SOURCE}/cached": 0,
            f"{SOURCE}/failed": 0,
            f"{SOURCE}/left_out": 1,
        }

    def test_a_source_that_leaves_nothing_out_records_a_zero(self):
        """Counter-example (row 3): the one where the JSON fails instead (R8.25)."""
        counts = {"held": 3, "converted": 2, "cached": 0, "failed": 1, "left_out": 0}

        recorded = count_metrics(kind="convert", source=SOURCE, counts=counts)

        assert (recorded[f"{SOURCE}/failed"], recorded[f"{SOURCE}/left_out"]) == (1, 0)

    def test_a_convert_that_does_not_say_what_it_left_out_is_refused(self):
        """The one where the caller forgot the count: refused, not recorded as absent."""
        counts = {"held": 3, "converted": 3, "cached": 0, "failed": 0}

        with pytest.raises(ValueError, match="no left_out count"):
            count_metrics(kind="convert", source=SOURCE, counts=counts)
