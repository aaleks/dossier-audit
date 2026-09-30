"""R8.18 — an issue that holds fewer comments than it counts says so in its note.

Jira embeds an issue's comments in its payload and says how many there are in
`comment.total`. A payload holding fewer is a document with part of its thread
missing, and a note that looked complete would let a stage report a thread's
conclusion from its first half.
"""

from __future__ import annotations

import json
from pathlib import Path

from dossier.domain.jira_issue import note

ISSUE = Path(__file__).resolve().parents[1] / "fixtures" / "jira" / "INC-4821.json"


def unchanged(text: str) -> str:
    return text


def with_thread(thread: dict | None) -> bytes:
    """`INC-4821` holding `thread` as its `comment` field, or none at all."""
    issue = json.loads(ISSUE.read_bytes())
    if thread is None:
        del issue["fields"]["comment"]
    else:
        issue["fields"]["comment"] = thread
    return json.dumps(issue).encode("utf-8")


def comments(count: int) -> list[dict]:
    return [
        {
            "author": {"displayName": "m.keller"},
            "created": f"2026-08-05T1{n}:00:00.000+0000",
            "body": f"Update {n}.",
        }
        for n in range(count)
    ]


class TestANoteSaysWhenCommentsAreMissing:
    """R8.18 — a thread shorter than its count is said to be."""

    def test_a_short_thread_says_how_many_are_missing_after_the_last_comment(self):
        """Row 1: the one where Jira counts 7 and sent 5."""
        written = note(with_thread({"comments": comments(5), "total": 7}), markup=unchanged)

        assert written.endswith("Update 4.\n\n2 of 7 comments are not in this snapshot.\n")

    def test_a_whole_thread_says_nothing_about_it(self):
        """Counter-example, row 2: the one where Jira counts 2 and sent 2."""
        written = note(with_thread({"comments": comments(2), "total": 2}), markup=unchanged)

        assert "not in this snapshot" not in written

    def test_no_comment_field_means_no_comments_section(self):
        """Counter-example, row 3: the one where the payload has no `comment` at all."""
        written = note(with_thread(None), markup=unchanged)

        assert "## Comments" not in written
        assert "not in this snapshot" not in written

    def test_a_thread_jira_sent_none_of_still_says_so(self):
        """Row 1 at its limit: the one where Jira counts 3 and sent none."""
        written = note(with_thread({"comments": [], "total": 3}), markup=unchanged)

        assert written.endswith("## Comments\n\n3 of 3 comments are not in this snapshot.\n")

    def test_one_missing_is_said_as_surely_as_two(self):
        """Row 4: the one where Jira counts 6 and sent 5."""
        written = note(with_thread({"comments": comments(5), "total": 6}), markup=unchanged)

        assert written.endswith("Update 4.\n\n1 of 6 comments are not in this snapshot.\n")

    def test_a_thread_of_one_that_sent_none_still_says_so(self):
        """Row 5: the one where Jira counts 1 and sent none."""
        written = note(with_thread({"comments": [], "total": 1}), markup=unchanged)

        assert written.endswith("## Comments\n\n1 of 1 comments are not in this snapshot.\n")
