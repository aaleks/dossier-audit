"""R011.7 — a `dossier eval` links its MLflow run to the dataset of the gold set it
scored, and names a stale one.

The application half: what `start_eval` puts on the run, and what `log_dataset`
sends. The acceptance test beside this one proves a person running the two commands
sees it; this one pins the record's shape, and in particular that staleness is a
**tag**.

A tag rather than a param because it is a property of the run as a whole and
because filtering a list of runs is how a stale dataset gets noticed at all. A
param would put it beside the model and the gold set, where nobody scans for it.
"""

from __future__ import annotations

from tests.fakes import FakeTracker

from dossier.application.eval import start_eval
from dossier.domain.gold import gold_set_hash

GOLD_FILES = {
    "INC-4821.json": b'{"document": "INC-4821", "verified_by": "a.aleks", '
    b'"verified_at": "2026-08-14", "fields": {"severity": {"value": "major"}}}',
}
RUN_ID = "20260806T142203Z-4f1a"
EXPERIMENT = "dossier-audit/incident-audit/eval/incidents"
DATASET_ID = "d-18afc31376cb427a"


def _open_run(tracker: FakeTracker, **kwargs) -> None:
    start_eval(
        tracker,
        experiment=EXPERIMENT,
        pipeline="incident-audit",
        run_id=RUN_ID,
        model="gemini:gemini-3.5-flash-lite",
        gold="gold/incidents",
        gold_files=GOLD_FILES,
        **kwargs,
    )


class TestAnEvalLinksTheDatasetItScoredAgainst:
    """R11.7 — the eval run says which dataset it was measured against."""

    def test_the_dataset_is_sent_as_an_input_of_the_run(self):
        """Example 1: the one where the run carries its dataset.

        `log_dataset` sends and returns nothing, like every other `Tracker`
        method: the dataset was *found* through `DatasetRegistry`, which is the
        port allowed to read, and this only says which one it was (R0.10).
        """
        tracker = FakeTracker()
        _open_run(tracker)

        tracker.log_dataset(name="incidents", dataset_id=DATASET_ID, digest="61da2705")

        assert tracker.runs[-1].inputs == [
            {"name": "incidents", "dataset_id": DATASET_ID, "digest": "61da2705"}
        ]

    def test_a_stale_dataset_is_a_tag_and_the_gold_hash_is_the_one_scored(self):
        """Example 2: the one where the dataset is behind what was scored.

        Both hashes are on the run and they differ: `dossier.gold_hash` is the set
        that *was* scored, because that is what the figures are about, and the tag
        says the published dataset is not it.
        """
        tracker = FakeTracker()

        _open_run(tracker, dataset_stale=True)

        tags = tracker.runs[-1].tags
        assert tags["dossier.dataset_stale"] == "true"
        assert tags["dossier.gold_hash"] == gold_set_hash(GOLD_FILES)

    def test_a_matching_dataset_leaves_no_stale_tag_at_all(self):
        """Counter-example: the one where the two agree.

        Absent rather than `false`. A tag reading `dossier.dataset_stale=false` on
        every healthy run is noise in the place the signal has to be found, and it
        would make a filter for staleness match every run ever recorded.
        """
        tracker = FakeTracker()

        _open_run(tracker)

        assert "dossier.dataset_stale" not in tracker.runs[-1].tags

    def test_an_eval_that_records_no_run_can_link_nothing(self):
        """Counter-example (row 5): the one where no run was opened.

        A comparison records no run (R7.8), and a tracker asked to record into
        nothing says so rather than inventing a run to hold the link — the same
        `FakeTrackerError` that guards every other out-of-order record.
        """
        import pytest
        from tests.fakes import FakeTrackerError

        tracker = FakeTracker()

        with pytest.raises(FakeTrackerError):
            tracker.log_dataset(name="incidents", dataset_id=DATASET_ID, digest="61da2705")
