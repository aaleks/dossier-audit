"""R2.2 — an unchanged normalised payload produces no new snapshot.

Re-fetching is cheap and sometimes unavoidable. Re-storing is not, and a second
snapshot of identical content would make the store lie about what changed.

The rows below are the rule's example table, transcribed. The specs write hashes
as 8-character display prefixes (`c4a70b93`); real digests are computed here.
"""

from __future__ import annotations

import pytest

from dossier.domain.hashing import content_hash
from dossier.domain.sync import Change, classify, normalise

AUDIT_NOTE = content_hash(b"# Audit note - Q3 sampling\n")  # c4a70b93 in the specs
INC_4822_WAS = content_hash(b"# INC-4822\n\nstatus: open\n")  # 0e52dd18
INC_4822_NOW = content_hash(b"# INC-4822\n\nstatus: resolved\n")  # 77c1b40a


class TestClassify:
    """R2.2 — a fetch is not a write."""

    def test_an_identical_payload_is_unchanged(self):
        """The one where the file came back exactly as it was.

        Example 1: `audit-note.pdf`, already at that hash. Only `last_seen` moves.
        """
        outcome = classify(recorded_hash=AUDIT_NOTE, computed_hash=AUDIT_NOTE)

        assert outcome is Change.UNCHANGED
        assert outcome.writes_snapshot is False

    def test_an_unknown_item_is_new(self):
        """The one where nothing has been held before."""
        outcome = classify(recorded_hash=None, computed_hash=AUDIT_NOTE)

        assert outcome is Change.NEW
        assert outcome.writes_snapshot is True

    def test_a_different_payload_is_changed(self):
        """Example 3: the one where `INC-4822` actually moved."""
        outcome = classify(recorded_hash=INC_4822_WAS, computed_hash=INC_4822_NOW)

        assert outcome is Change.CHANGED
        assert outcome.writes_snapshot is True

    def test_fetching_the_same_file_five_times_still_writes_nothing(self):
        """Example 2: the one where repetition changes no answer.

        The claim in the rule is a count -- "regardless of how many times it is
        fetched" -- so this asserts the count, not just the verdict.
        """
        outcomes = [
            classify(recorded_hash=AUDIT_NOTE, computed_hash=AUDIT_NOTE) for _ in range(5)
        ]

        assert outcomes == [Change.UNCHANGED] * 5
        assert sum(outcome.writes_snapshot for outcome in outcomes) == 0

    def test_a_payload_differing_only_outside_the_projection_is_unchanged(self):
        """Counter-example (row 4): the one normalisation exists for.

        Two fetches of the same Jira issue whose rendered HTML was regenerated.
        Different bytes on the wire, same content hash, so nothing is stored --
        which is the whole reason R2.10 projects before hashing.
        """
        fields = ["key", "status"]
        monday = b'{"key":"INC-4822","status":"open","renderedDescription":"<p>a</p>"}'
        tuesday = b'{"key":"INC-4822","status":"open","renderedDescription":"<div>a</div>"}'

        recorded = content_hash(normalise(monday, fields=fields))
        computed = content_hash(normalise(tuesday, fields=fields))

        assert classify(recorded_hash=recorded, computed_hash=computed) is Change.UNCHANGED

    def test_every_outcome_says_whether_it_writes(self):
        """The one where the caller cannot forget to ask.

        R2.5 counts snapshots written. If `writes_snapshot` were left to the call
        site, that count would be a second implementation of this rule.
        """
        assert {change: change.writes_snapshot for change in Change} == {
            Change.NEW: True,
            Change.CHANGED: True,
            Change.UNCHANGED: False,
        }

    @pytest.mark.parametrize(
        ("recorded", "computed"),
        [
            pytest.param("c4a70b93", AUDIT_NOTE, id="recorded-is-a-display-prefix"),
            pytest.param(AUDIT_NOTE, "c4a70b93", id="computed-is-a-display-prefix"),
        ],
    )
    def test_a_display_prefix_is_not_a_hash(self, recorded: str, computed: str):
        """The one where two truncated hashes would compare equal by accident.

        Comparing prefixes is how two different documents get called unchanged.
        """
        with pytest.raises(ValueError):
            classify(recorded_hash=recorded, computed_hash=computed)
