"""A Jira issue, read as the note this playground's Jira wants.

`dossier` converts a Jira issue out of the box. The connector reports an issue
as `application/vnd.dossier.jira-issue+json` (R1.14), and `jira-issue-markdown`,
which ships beside it, claims that pair and writes the note spec 008 describes
(R8.16). This package claims the same pair to write a different note, and is
written the way exercise 03's package is: through the entry-point group, with no
edit to `dossier` (R8.7).

What it decides differently from the shipped converter, and why each difference
is a decision:

* **Labels are part of the document.** The shipped note leaves them out. Here
  they are a line of their own, sorted: a label set has no order Jira means
  anything by, so the note does not change when the same labels arrive in a
  different order (R0.4).
* **Less of a comment.** Its author, not the time beside it, and nothing said
  when the payload holds fewer comments than it counts (R8.18). The seeded
  issues have no comments; a Jira whose threads matter wants the shipped note.

What it decides the same way:

* **Which fields are the document**, apart from the labels. A Jira issue payload
  is mostly machinery: avatars, permission ids, a `self` URL per nested object,
  custom fields by the hundred. The document is the summary, the description,
  and the handful of fields a person reading the incident would want.
  Everything else is dropped -- and dropping it is not tidying, it is what
  makes a span searchable: `{{documents}}` carrying forty kilobytes of avatar
  URLs is forty kilobytes a model can ground a fabricated quote in.
* **The description and comments are wiki markup.** That is what Jira's REST
  API version 2 answers them as, and what `seed_jira.py` writes. They are read
  with the library the shipped converter uses, the same two ways (R8.17): no
  backslash escapes, since a model quotes `3*2` and not `3\\*2`, and `\\r\\n` as
  `\\n`. The library is pinned exactly in `pyproject.toml`, because what it
  writes is inside the artifact and the convert key names this converter's
  version, not the library's: moving the pin is a new `version` here (R5.4).
* **A fixed order.** Written in the order below on every machine, never in the
  order the JSON happened to arrive in. Two runs over the same issue must
  produce the same bytes or the convert key means nothing (R8.1, R0.4).
* **No clock, no environment, no network.** The only input is `payload`.

Two converters now claim one pair, and `dossier` will not choose between them by
installation order. A workspace chooses, by naming one under `converters:` in
`sources.yaml` (R8.13) -- `solution/workspace/sources.yaml` names this one. Not
shipped with `dossier`, and not a proposal that it should be: which fields are
the document is a decision a workspace makes about its own source.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from jira2markdown import convert as _jira2markdown
from jira2markdown.elements import MarkupElements
from jira2markdown.markup.text_effects import EscSpecialChars

# The type the Jira connector reports an issue as (R1.14). Spelled out rather
# than imported from `dossier`: a package claiming a pair from outside names it
# the way any third party would, and it is a label on a snapshot, not a code
# path this package depends on.
JIRA_ISSUE = "application/vnd.dossier.jira-issue+json"

# Written in this order, always. The label is what a reader sees; the key is
# where the value is read from under `fields`.
HEADERS = (
    ("Status", ("status", "name")),
    ("Type", ("issuetype", "name")),
    ("Priority", ("priority", "name")),
    ("Resolution", ("resolution", "name")),
    ("Created", ("created",)),
    ("Updated", ("updated",)),
)


class JiraIssueConversionFailed(ValueError):
    """The payload is not JSON, or not an object with the shape of an issue."""


class JiraIssueMarkdownConverter:
    """A Jira issue to the `markdown` kind, labels included."""

    # Not `jira-issue-markdown`. The id and the version are how `dossier` tells
    # two claims apart: a converter sharing the shipped one's id and version is
    # taken for that converter listed twice, and which of the two wrote an
    # artifact would then turn on installation order, under a convert key
    # saying it made no difference (R8.2, R5.6).
    id = "play-jira-issue-markdown"
    # Every change to what `convert` writes raises this, because the version is
    # in the convert key and an artifact produced by 1.0.0 must never be served
    # for a request that 1.1.0 would answer differently (R5.4, R8.2).
    version = "1.0.0"
    media_type = JIRA_ISSUE
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The issue as a note: a heading, the fields worth reading, the description.

        `options` is accepted and unused, as the shipped converters accept it:
        the interface is uniform, and an option nobody reads still lands in the
        key, so it produces its own cache entry rather than a silent no-op.
        """
        issue = _parsed(payload)
        fields = issue.get("fields")
        if not isinstance(fields, dict):
            # A JSON object that is not an issue fails here, named, against the
            # one document -- not four fields further on with an AttributeError
            # that says nothing about which document or which source.
            raise JiraIssueConversionFailed(
                f"{self.id}: the payload has no `fields` object, so it is not a Jira issue"
            )

        key = str(issue.get("key") or "").strip()
        summary = str(fields.get("summary") or "").strip()

        lines: list[str] = [_heading(key, summary), ""]

        for label, path in HEADERS:
            value = _at(fields, path)
            if value:
                lines.append(f"**{label}:** {value}")

        labels = sorted(
            label.strip()
            for label in fields.get("labels") or []
            if isinstance(label, str) and label.strip()
        )
        if labels:
            # The field this package adds. Sorted, because the set is the
            # document and the order Jira listed it in is not.
            lines.append(f"**Labels:** {', '.join(labels)}")

        attachments = [
            str(item.get("filename"))
            for item in fields.get("attachment") or []
            if isinstance(item, dict) and item.get("filename")
        ]
        if attachments:
            # Named, never inlined. Each of these is its own document with its
            # own key, snapshot and ledger row (R1.6); copying their text in
            # here would put the same sentence in two artifacts and let a span
            # be grounded in the wrong one.
            lines.append(f"**Attachments:** {', '.join(sorted(attachments))}")

        description = str(fields.get("description") or "").strip()
        if description:
            lines += ["", "## Description", "", _markdown(description)]

        comments = _comments(fields)
        if comments:
            lines += ["", "## Comments", ""]
            for author, body in comments:
                lines += [f"**{author}**", "", body, ""]

        return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _markdown(markup: str) -> str:
    """Jira wiki markup as markdown, unescaped and with `\n` line endings.

    The summary and the fields are not passed through here: Jira shows them as
    typed and never renders them, so neither does the note.
    """
    elements = MarkupElements()
    elements.remove(EscSpecialChars)
    return _jira2markdown(markup.replace("\r\n", "\n"), elements=elements).strip()


def _heading(key: str, summary: str) -> str:
    """`# PLAY-1 -- Checkout timeouts ...`, in the corpus notes' own shape.

    The heading a folder note carries and the shipped converter writes, so a
    prompt written against one reads the other, and a `match` in the stub's
    reply file tells two issues apart on the line a person would use.
    """
    if key and summary:
        return f"# {key} — {summary}"
    return f"# {key or summary}".rstrip() or "# (untitled issue)"


def _parsed(payload: bytes) -> dict:
    """The payload as an object, or a failure naming this converter.

    A JSON array, a bare string and undecodable bytes all end here rather than
    three lines further on with a `TypeError` about `.get`.
    """
    try:
        issue = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JiraIssueConversionFailed(
            f"play-jira-issue-markdown: the payload is not UTF-8 JSON: {error}"
        ) from None
    if not isinstance(issue, dict):
        raise JiraIssueConversionFailed(
            f"play-jira-issue-markdown: expected a JSON object, got {type(issue).__name__}"
        )
    return issue


def _at(fields: Mapping[str, object], path: tuple[str, ...]) -> str:
    """`("status", "name")` as `fields["status"]["name"]`, or "" at the first miss."""
    current: object = fields
    for step in path:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(step)
    return "" if current is None else str(current).strip()


def _comments(fields: Mapping[str, object]) -> list[tuple[str, str]]:
    """Each comment as (author, body), in the order Jira returned them.

    Jira's order is the document's order: a comment thread read out of sequence
    is a different document. Not sorted here for that reason -- sorting is for
    things whose order carries no meaning, like the labels above (R0.4 is about
    removing *accidental* variation, not about imposing an order on a sequence
    that has one).
    """
    container = fields.get("comment")
    if not isinstance(container, Mapping):
        return []
    found = []
    for comment in container.get("comments") or []:
        if not isinstance(comment, Mapping):
            continue
        author = comment.get("author")
        name = ""
        if isinstance(author, Mapping):
            name = str(author.get("displayName") or author.get("name") or "").strip()
        body = str(comment.get("body") or "").strip()
        if body:
            found.append((name or "(unknown)", _markdown(body)))
    return found
