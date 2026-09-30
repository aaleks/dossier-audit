"""R8.30 — `confluence-page-markdown` writes a page's comments after its body,
each under its author and time, in thread order.

With `comments: true` a page is held as `{"page":…,"comments":[…]}`, each part as
Confluence sent it (R1.23). `81920114-comments.json` is a Data Center 9.2.21's
`child/comment?depth=all` answer with the fixtures' content: `m.keller`'s comment
`81920501`, then `a.aleks`'s reply `81920502`, which names its parent only by id.

As in R8.19's test, the domain is handed a marker for `markup`, so a test can see
which HTML went through it. Row 2 goes through the converter, where `markdownify`
writes it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.domain.confluence_page import note
from dossier.infrastructure.converters.confluence_page_markdown import (
    ConfluencePageMarkdownConverter,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "confluence"
PAGE = (FIXTURE / "81920114.json").read_bytes()
COMMENTS = (FIXTURE / "81920114-comments.json").read_bytes()
HELD = b'{"page":' + PAGE + b',"comments":[' + COMMENTS + b"]}"
BODIES = [c["body"]["export_view"]["value"] for c in json.loads(COMMENTS)["results"]]


def marked(html: str) -> str:
    """What went through `markup`, visibly: `«…»` around exactly what was given."""
    return f"«{html}»"


def held_with(answers: list[dict]) -> bytes:
    return b'{"page":' + PAGE + b',"comments":' + json.dumps(answers).encode() + b"}"


class TestAPagesCommentsFollowItsBody:
    """R8.30 — `## Comments` after the body, a comment then its replies."""

    def test_a_comment_and_its_reply_follow_the_body(self):
        """Row 1: the one where `a.aleks` replies to `m.keller`."""
        written = note(HELD, markup=marked)

        body, comments = written.split("\n\n## Comments\n\n")
        assert body == note(PAGE, markup=marked).rstrip("\n")
        assert comments.split("\n") == [
            "**m.keller** · 2026-08-05T17:10:00.000Z",
            "",
            f"«{BODIES[0]}»",
            "",
            "**a.aleks** · 2026-08-05T17:25:00.000Z · reply to m.keller",
            "",
            f"«{BODIES[1]}»",
            "",
        ]

    def test_a_reply_to_a_reply_names_the_reply_it_answers(self):
        """Row 6: the one where `m.keller` answers `a.aleks`'s reply."""
        answers = json.loads(COMMENTS)
        reply = answers["results"][1]
        answer = json.loads(json.dumps(reply))
        answer["id"] = "81920503"
        answer["history"]["createdBy"]["displayName"] = "m.keller"
        answer["ancestors"] = [*reply["ancestors"], {"id": "81920502", "type": "comment"}]
        answers["results"].append(answer)

        heading = note(held_with([answers]), markup=marked).split("\n")[-4]

        assert heading.startswith("**m.keller** · ")
        assert heading.endswith(" · reply to a.aleks")

    def test_a_comments_body_is_written_as_a_pages_is(self):
        """Row 2: the one where the comment's bold survives as markdown."""
        answers = json.loads(COMMENTS)
        answers["results"][0]["body"]["export_view"]["value"] = (
            "<p><strong>Root cause:</strong> expired certificate</p>"
        )

        written = ConfluencePageMarkdownConverter().convert(held_with([answers]), {})

        assert "\n\n**Root cause:** expired certificate\n" in written.decode("utf-8")

    def test_a_page_held_without_comments_has_no_comments_heading(self):
        """Counter-example (row 3): the one where the page is held as R1.17 holds it."""
        assert "## Comments" not in note(PAGE, markup=marked)

    def test_a_page_with_no_comment_has_the_note_it_has_without_them(self):
        """Counter-example (row 4): the one where `comments:` was on and found none."""
        empty = {"results": [], "start": 0, "limit": 50, "size": 0, "_links": {}}

        assert note(held_with([empty]), markup=marked) == note(PAGE, markup=marked)

    def test_comments_without_their_page_are_not_a_page(self):
        """Counter-example (row 5): the one where the envelope holds no `page`."""
        with pytest.raises(ValueError, match="not a rendered Confluence page"):
            note(b'{"comments":[' + COMMENTS + b"]}", markup=marked)

        with pytest.raises(ValueError, match="confluence-page-markdown"):
            ConfluencePageMarkdownConverter().convert(b'{"comments":[' + COMMENTS + b"]}", {})
