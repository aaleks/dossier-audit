"""A Jira issue, read as the note a person reads (spec 008, R8.16, R8.17).

The Jira connector holds an issue as the JSON Jira sent, labelled as a Jira
issue rather than as JSON (R1.14), and this is the converter that claims that
label. Which fields are the note, and in which order, is the domain's decision
(`dossier.domain.jira_issue.note`). What is decided here is how Jira wiki markup
-- the description and each comment, as REST API version 2 answers them on both
Cloud and Data Center -- becomes markdown.

[`jira2markdown`](https://github.com/catcombo/jira2markdown) does it, with two
changes from its defaults, both for the reason `docling-markdown` turns its
escapes off: the artifact is text a span is searched in, not markdown for a
renderer (R8.17).

* **Nothing is escaped.** The library backslash-escapes a `*` that is not
  emphasis, so `3*2` would be written `3\\*2`. A model quotes `3*2`.
* **`\\r\\n` becomes `\\n`.** Data Center sends wiki markup with Windows line
  endings, and a note mixing them with the `\\n` it is assembled with would be
  two conventions in one file.
"""

from __future__ import annotations

from collections.abc import Mapping

from dossier.domain.conversion import JIRA_ISSUE
from dossier.domain.jira_issue import note


class JiraIssueMarkdownConverter:
    """A Jira issue to the `markdown` kind."""

    id = "jira-issue-markdown"
    # Raised whenever what `convert` writes could change for the same payload --
    # including when `jira2markdown`'s pin moves, since the library's version is
    # not in the key and this one is (R5.4, R8.2).
    version = "1.0.0"
    media_type = JIRA_ISSUE
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The issue as a note, UTF-8, ending in one newline.

        `options` is accepted and unused, as the shipped converters accept it:
        an option nobody reads still lands in the key, so it produces its own
        cache entry rather than a silent no-op.

        A payload that is not an issue fails naming this converter, and R8.6
        keeps the failure to its one document.
        """
        try:
            written = note(payload, markup=markdown)
        except ValueError as error:
            raise ValueError(f"{self.id}: {error}") from None
        return written.encode("utf-8")


def markdown(markup: str) -> str:
    """Jira wiki markup as markdown, unescaped and with `\\n` line endings (R8.17)."""
    from jira2markdown import convert
    from jira2markdown.elements import MarkupElements
    from jira2markdown.markup.text_effects import EscSpecialChars

    elements = MarkupElements()
    elements.remove(EscSpecialChars)
    return convert(markup.replace("\r\n", "\n"), elements=elements)
