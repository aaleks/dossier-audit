"""R8.19 — `confluence-page-markdown` converts a page to a note of its title,
space, version, time and author, and its body, and of nothing else in the payload.

Which parts are the note, and in which order, is a decision over the parsed page,
so it is made in the domain: `note` is handed the payload and the function that
turns the rendered HTML into markdown, and decides everything else. Here that
function is a marker, so a test can see what went through it without depending
on what a library makes of it (R8.20).

`81920114` is `tests/fixtures/confluence/81920114.json`: a payload in the shape
Confluence Data Center 9.2 sends, with the fixture's content (specs/_fixtures.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.domain.confluence_page import note

PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "confluence" / "81920114.json"


def marked(html: str) -> str:
    """The body, visibly passed through: `«…»` around exactly what was given."""
    return f"«{html}»"


def lines(text: str) -> list[str]:
    return text.split("\n")


class TestAPageConvertsToANoteOfWhatAPersonReads:
    """R8.19 — the title, four lines about the version, then the body."""

    def test_the_note_opens_with_the_title_and_the_lines_about_its_version(self):
        """Example 1: the one where `OPS-114` is version 37, written by `m.keller`."""
        written = lines(note(PAGE.read_bytes(), markup=marked))

        assert written[:6] == [
            "# OPS-114 Incident escalation procedure",
            "",
            "**Space:** OPS",
            "**Version:** 37",
            "**Updated:** 2026-08-05T16:02:00.000Z",
            "**By:** m.keller",
        ]

    def test_the_body_follows_as_markup_made_it(self):
        """Example 1, continued: the one where the body is handed over whole."""
        page = json.loads(PAGE.read_bytes())
        body = page["body"]["export_view"]["value"]

        written = note(PAGE.read_bytes(), markup=marked)

        assert written.endswith(f"\n\n«{body}»\n")

    def test_the_payloads_machinery_is_not_in_the_note(self):
        """Counter-example, row 3: the one where the JSON around the page is left out."""
        payload = PAGE.read_bytes()

        written = note(payload, markup=lambda html: "")

        for machinery in (
            "_links",
            "_expandable",
            "https://confluence.example.internal/rest/api/space/OPS",
            "Rota link updated",
            "8aa98087",
        ):
            assert machinery.encode() in payload
            assert machinery not in written

    def test_a_line_the_page_has_no_value_for_is_left_out(self):
        """The one where the version names nobody: no `**By:**` line, not an empty one."""
        page = json.loads(PAGE.read_bytes())
        del page["version"]["by"]

        written = note(json.dumps(page).encode("utf-8"), markup=marked)

        assert "**By:**" not in written
        assert "**Version:** 37" in written

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(b'{"id": "81920114"}', id="no body"),
            pytest.param(b"<html>login</html>", id="not JSON"),
            pytest.param(b'["81920114"]', id="not an object"),
        ],
    )
    def test_a_payload_that_is_not_a_rendered_page_is_refused_by_name(self, payload: bytes):
        """Counter-example, row 4: the one where the payload has no `body.export_view`."""
        with pytest.raises(ValueError, match="not a rendered Confluence page"):
            note(payload, markup=marked)
