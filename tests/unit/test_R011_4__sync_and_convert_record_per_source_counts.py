"""R11.4 — a `dossier sync` or `dossier convert` is one MLflow run of per-source
counts, with no traces.

Every figure recorded is one dossier already computes and prints (R2.13, R8.8):
MLflow is a second place to read it, never a second way of computing it. Names
use `/` so MLflow's UI groups every count of one source under its id.

The decision of which counts a command records, and under which names, is pure;
recording them is the tracker port's.
"""

from __future__ import annotations

from dossier.domain.tracking import count_metrics


class TestSyncAndConvertRecordPerSourceCounts:
    """R11.4 — one metric per count, per source, named under the source."""

    def test_a_sync_records_the_counts_it_prints(self):
        """Example 1: the one where `incidents-jira` holds 420 items, 18 changed and 2 new."""
        counts = {
            "known": 420,
            "changed": 18,
            "new": 2,
            "returned": 0,
            "fetched": 20,
            "failed": 0,
        }

        assert count_metrics(kind="sync", source="incidents-jira", counts=counts) == {
            "incidents-jira/known": 420,
            "incidents-jira/changed": 18,
            "incidents-jira/new": 2,
            "incidents-jira/returned": 0,
            "incidents-jira/fetched": 20,
            "incidents-jira/failed": 0,
        }

    def test_a_convert_records_the_counts_it_prints(self):
        """Example 2: the one converting `incidents-manual`'s three documents, none cached."""
        counts = {"held": 3, "converted": 3, "cached": 0, "failed": 0}

        assert count_metrics(kind="convert", source="incidents-manual", counts=counts) == {
            "incidents-manual/held": 3,
            "incidents-manual/converted": 3,
            "incidents-manual/cached": 0,
            "incidents-manual/failed": 0,
        }

    def test_a_source_where_nothing_changed_is_recorded_with_its_zeros(self):
        """Counter-example (row 3): the one where `procedures-confluence` did nothing.

        Recorded, not omitted: a missing source is indistinguishable from a
        skipped one (R2.13).
        """
        counts = {"known": 3, "changed": 0, "new": 0, "returned": 0, "fetched": 0, "failed": 0}

        recorded = count_metrics(kind="sync", source="procedures-confluence", counts=counts)

        assert recorded == {
            "procedures-confluence/known": 3,
            "procedures-confluence/changed": 0,
            "procedures-confluence/new": 0,
            "procedures-confluence/returned": 0,
            "procedures-confluence/fetched": 0,
            "procedures-confluence/failed": 0,
        }
