"""R8.17 — an issue's description and comments are wiki markup, written as markdown.

Its summary and fields are written as text. `jira-issue-markdown` hands the
description and each comment to `jira2markdown`, with two changes from its
defaults, both for the reason `docling-markdown` turns its escapes off: the
artifact is text a span is searched in, not markdown for a renderer. Nothing is
backslash-escaped, and Jira's `\\r\\n` becomes `\\n`.

What the library does with each construct is the library's to prove. These rows
are the boundary: which text reaches it, and the two changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.domain.conversion import JIRA_ISSUE
from dossier.infrastructure.converters.jira_issue_markdown import JiraIssueMarkdownConverter

ISSUE = Path(__file__).resolve().parents[1] / "fixtures" / "jira" / "INC-4821.json"


def converted(**fields) -> str:
    """`INC-4821`, with `fields` replaced where given, as the converter writes it."""
    issue = json.loads(ISSUE.read_bytes())
    issue["fields"].update(fields)
    payload = json.dumps(issue).encode("utf-8")
    return JiraIssueMarkdownConverter().convert(payload, {}).decode("utf-8")


def thread(body: str) -> dict:
    comment = {"author": {"displayName": "m.keller"}, "created": "", "body": body}
    return {"comments": [comment], "total": 1}


class TestWikiMarkupIsWrittenAsMarkdown:
    """R8.17 — markup where Jira renders it, text where Jira shows it as typed."""

    def test_a_heading_and_a_list_become_markdown_and_crlf_becomes_lf(self):
        """Row 1: the one where Data Center sent `\\r\\n` line endings."""
        written = converted(description="h2. Impact\r\n* 42 minutes of declined payments")

        assert "## Impact\n- 42 minutes of declined payments\n" in written
        assert "\r" not in written

    def test_a_link_in_a_comment_becomes_a_markdown_link(self):
        """Row 2: the one where a comment links the rollback."""
        written = converted(comment=thread("see [the rollback|https://git.example/r/77]"))

        assert "see [the rollback](https://git.example/r/77)" in written

    def test_nothing_is_escaped(self):
        """Row 3: the one where a model would quote `lb_acq_01`, not `lb\\_acq\\_01`."""
        written = converted(description="pool lb_acq_01 held 3*2 connections")

        assert "pool lb_acq_01 held 3*2 connections" in written
        assert "\\" not in written

    def test_the_summary_is_written_as_typed(self):
        """Counter-example, row 4: the one where a summary looks like markup."""
        written = converted(summary="*Sev 1* card declines")

        assert written.startswith("# INC-4821 — *Sev 1* card declines\n")

    def test_the_fixture_issue_reads_as_its_description_says(self):
        """Every construct `INC-4821` uses, end to end: a table, a list, a heading."""
        written = JiraIssueMarkdownConverter().convert(ISSUE.read_bytes(), {}).decode("utf-8")

        assert "- total exposure CHF 48'200\n" in written
        assert "|Time|Event|\n|---|---|\n|09:12|declines start|" in written


class TestTheConverterDeclaresItself:
    """R8.2's fields, for the pair R1.14 labels an issue with."""

    def test_it_claims_a_jira_issue_as_markdown(self):
        converter = JiraIssueMarkdownConverter()

        assert (converter.id, converter.media_type, converter.kind) == (
            "jira-issue-markdown",
            JIRA_ISSUE,
            "markdown",
        )

    def test_it_is_installed(self):
        """Registered through `dossier.converters`, like every other (R8.7)."""
        from dossier.infrastructure.converters.registry import installed_converters

        assert "jira-issue-markdown" in {c.id for c in installed_converters()}

    def test_a_payload_that_is_not_an_issue_fails_naming_the_converter(self):
        """R8.16 row 7: the failure names which converter refused, and why."""
        with pytest.raises(ValueError, match="jira-issue-markdown: not a Jira issue"):
            JiraIssueMarkdownConverter().convert(b'{"key": "INC-4821"}', {})
