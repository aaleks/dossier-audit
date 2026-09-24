"""R8.16 — a Jira issue converts to a note of its key, summary, fields, description, comments.

And of nothing else in the payload. Which fields are the note, and in which
order, is a decision over the parsed issue, so it is made in the domain: `note`
is handed the payload and the function that turns wiki markup into markdown, and
decides everything else. Here that function is a marker, so a test can see which
text went through it without depending on what a library makes of it (R8.17).

`INC-4821` is `tests/fixtures/jira/INC-4821.json`: a payload in the shape a real
Jira Server sends, with the fixture's content (specs/_fixtures.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.domain.jira_issue import note

ISSUE = Path(__file__).resolve().parents[1] / "fixtures" / "jira" / "INC-4821.json"


def marked(text: str) -> str:
    """Wiki markup, visibly passed through: `«…»` around exactly what was given."""
    return f"«{text}»"


def payload(**fields) -> bytes:
    """`INC-4821` with `fields` replaced where given."""
    issue = json.loads(ISSUE.read_bytes())
    issue["fields"].update(fields)
    return json.dumps(issue).encode("utf-8")


def lines(text: str) -> list[str]:
    return text.split("\n")


class TestAnIssueConvertsToANoteOfWhatAPersonReads:
    """R8.16 — the note, in order, and nothing else."""

    def test_the_note_opens_with_the_key_and_the_summary(self):
        """Row 1: the one where the heading is the issue as a person names it."""
        assert lines(note(ISSUE.read_bytes(), markup=marked))[0] == (
            "# INC-4821 — Card payments declined at checkout"
        )

    def test_the_fields_follow_in_a_fixed_order_and_an_absent_one_has_no_line(self):
        """Row 2: the one where the issue has no resolution."""
        written = lines(note(ISSUE.read_bytes(), markup=marked))

        assert written[1:8] == [
            "",
            "**Status:** Done",
            "**Type:** Incident",
            "**Priority:** High",
            "**Created:** 2026-08-05T09:12:00.000+0000",
            "**Updated:** 2026-08-06T08:41:00.000+0000",
            "**Attachments:** report.pdf",
        ]
        assert not any(line.startswith("**Resolution:**") for line in written)

    def test_a_resolution_the_issue_has_is_written_after_the_priority(self):
        """Row 2's other half: the line exists when the value does."""
        resolved = payload(resolution={"self": "…", "id": "1", "name": "Fixed"})

        written = lines(note(resolved, markup=marked))

        assert written[4:6] == ["**Priority:** High", "**Resolution:** Fixed"]

    def test_the_description_follows_the_fields_through_the_markup(self):
        """The description is wiki markup, and only the markup function reads it."""
        written = note(payload(description="h2. Impact"), markup=marked)

        assert "\n## Description\n\n«h2. Impact»\n" in written

    def test_comments_are_written_in_jiras_order_under_their_authors(self):
        """Row 3: the one where `m.keller` spoke first, so is written first."""
        written = note(ISSUE.read_bytes(), markup=marked)

        comments = written[written.index("## Comments") :]
        keller = comments.index("**m.keller** · 2026-08-05T10:02:00.000+0000")
        aleks = comments.index("**a.aleks** · 2026-08-06T08:41:00.000+0000")
        assert keller < aleks
        assert "«Loss figure confirmed with finance.»" in comments[aleks:]

    def test_the_description_comes_before_the_comments(self):
        """The order the heading, fields, description and thread are read in."""
        written = note(ISSUE.read_bytes(), markup=marked)

        assert written.index("## Description") < written.index("## Comments")

    def test_an_attachment_is_named_and_never_inlined(self):
        """Row 4: the one where `report.pdf` is its own document (R1.6)."""
        written = note(ISSUE.read_bytes(), markup=marked)

        assert "**Attachments:** report.pdf" in written
        assert "%PDF" not in written

    def test_the_summary_is_not_read_as_markup(self):
        """R8.17 row 4, where the domain decides it: a summary is shown as typed."""
        written = note(payload(summary="*Sev 1* card declines"), markup=marked)

        assert lines(written)[0] == "# INC-4821 — *Sev 1* card declines"

    def test_the_note_ends_with_one_newline(self):
        """A file ending in exactly one newline, whatever the payload ended with."""
        written = note(payload(comment={"comments": [], "total": 0}), markup=marked)

        assert written.endswith("»\n") and not written.endswith("\n\n")

    def test_nothing_else_in_the_payload_reaches_the_note(self):
        """Counter-example, row 6: avatars, `self` links and a custom field."""
        written = note(ISSUE.read_bytes(), markup=marked)

        assert "avatar" not in written
        assert "/rest/api/2/" not in written
        assert "Mitigation owner" not in written
        assert "jira.example.internal" not in written

    @pytest.mark.parametrize(
        "sent",
        [
            b'{"key": "INC-4821"}',
            b'{"key": "INC-4821", "fields": []}',
            b"[]",
            b"not json",
            b"\xff\xfe",
        ],
        ids=["no fields", "fields not an object", "an array", "not json", "not utf-8"],
    )
    def test_a_payload_that_is_not_an_issue_fails_saying_so(self, sent: bytes):
        """Counter-example, row 7: the one where the payload has no `fields` object.

        A `ValueError`, which R8.6 isolates to the one document.
        """
        with pytest.raises(ValueError, match="not a Jira issue"):
            note(sent, markup=marked)
