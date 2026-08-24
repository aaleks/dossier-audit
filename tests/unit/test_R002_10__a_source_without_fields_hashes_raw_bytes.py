"""R2.10 — a source that declares no `fields` hashes its payload as received.

Normalisation projects a structured payload onto declared fields. A payload with
no declared fields has nothing to project onto, and every byte of it counts.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from dossier.domain.hashing import content_hash
from dossier.domain.sync import normalise

AUDIT_NOTE = b"# Audit note - Q3 sampling\n\nManually prepared note.\n"

# A Jira issue as received: the fields the pipeline consumes, plus two that
# change on every fetch and are excluded by the projection.
JIRA_FIELDS = ["key", "summary", "status"]


def jira_payload(*, rendered: str, views: int) -> bytes:
    return json.dumps(
        {
            "key": "INC-4821",
            "summary": "Payment batch partially rejected",
            "status": "resolved",
            "renderedDescription": rendered,
            "viewCount": views,
        }
    ).encode()


class TestSourceWithoutFields:
    """R2.10 — no projection means every byte counts."""

    def test_a_folder_payload_is_hashed_exactly_as_received(self):
        """The one where a dropped file is its own content.

        Example 1: `audit-note.md` has no fields to project onto.
        """
        assert normalise(AUDIT_NOTE, fields=None) == AUDIT_NOTE
        assert content_hash(normalise(AUDIT_NOTE, fields=None)) == (
            hashlib.sha256(AUDIT_NOTE).hexdigest()
        )

    def test_a_trailing_space_is_a_real_edit(self):
        """Example 2: the one where whitespace counts, because nothing says it doesn't.

        The opposite of example 3 below, and deliberately so. For a structured
        payload, whitespace is rendering noise. For a file someone dropped in a
        folder, an edit is an edit.
        """
        edited = AUDIT_NOTE + b" "

        assert content_hash(normalise(edited, fields=None)) != content_hash(
            normalise(AUDIT_NOTE, fields=None)
        )


class TestSourceWithFields:
    """R2.10 — a declared projection is what makes R2.2 possible."""

    def test_a_field_outside_the_projection_does_not_change_the_hash(self):
        """Example 3: the one where re-rendered HTML is not a change.

        Without this, every item looks modified on every sync and the ledger
        stops meaning anything (R2.2).
        """
        monday = jira_payload(rendered="<p>Batch failed</p>", views=12)
        tuesday = jira_payload(rendered="<div>Batch failed</div>", views=97)

        assert normalise(monday, fields=JIRA_FIELDS) == normalise(tuesday, fields=JIRA_FIELDS)

    def test_a_field_inside_the_projection_does_change_the_hash(self):
        """The one that stops the projection from hiding everything.

        Without this row the rule is satisfied by a function returning a
        constant, which is exactly the shape a stub takes.
        """
        before = jira_payload(rendered="<p>x</p>", views=1)
        after = json.dumps(
            {
                "key": "INC-4821",
                "summary": "Payment batch fully rejected",
                "status": "resolved",
                "renderedDescription": "<p>x</p>",
                "viewCount": 1,
            }
        ).encode()

        assert normalise(before, fields=JIRA_FIELDS) != normalise(after, fields=JIRA_FIELDS)

    def test_the_order_fields_are_declared_in_does_not_matter(self):
        """R2.3 example 2: the projection is a set, ordered canonically."""
        payload = jira_payload(rendered="<p>x</p>", views=1)

        assert normalise(payload, fields=["key", "summary", "status"]) == normalise(
            payload, fields=["status", "key", "summary"]
        )

    def test_the_order_keys_arrive_in_does_not_matter(self):
        """The one where a server reorders its JSON and nothing downstream moves.

        R5.6 forbids relying on iteration order anywhere a hash is involved.
        """
        one = json.dumps({"key": "INC-4821", "summary": "a", "status": "open"}).encode()
        other = json.dumps({"status": "open", "key": "INC-4821", "summary": "a"}).encode()

        assert normalise(one, fields=JIRA_FIELDS) == normalise(other, fields=JIRA_FIELDS)

    def test_a_declared_field_the_payload_lacks_is_not_invented(self):
        """The one where a missing field is absent, not null.

        An absent field and a field explicitly set to null are different things
        to a source system, and collapsing them would make two genuinely
        different items hash alike.
        """
        without = json.dumps({"key": "INC-4821", "summary": "a"}).encode()
        with_null = json.dumps({"key": "INC-4821", "summary": "a", "status": None}).encode()

        assert normalise(without, fields=JIRA_FIELDS) != normalise(
            with_null, fields=JIRA_FIELDS
        )


class TestProjectionIsRejectedWhenMeaningless:
    """R2.10 row 4, and the sync-time half of R3.9."""

    def test_an_empty_projection_is_refused(self):
        """Counter-example (row 4): the one where `fields: []` is not `fields:`.

        An empty list is a projection onto nothing, which no payload satisfies.
        Treating it as "hash everything" would silently give a source the
        opposite of what it asked for.
        """
        with pytest.raises(ValueError):
            normalise(AUDIT_NOTE, fields=[])

    def test_a_projection_over_a_payload_that_is_not_structured_is_an_error(self):
        """The one R3.9's counter-example defers to sync time.

        A source declaring `fields` whose payload turns out to be a PDF is not a
        load-time error -- load time never fetches a payload. It is an error
        here, where the payload is finally in hand.
        """
        with pytest.raises(ValueError):
            normalise(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", fields=JIRA_FIELDS)
