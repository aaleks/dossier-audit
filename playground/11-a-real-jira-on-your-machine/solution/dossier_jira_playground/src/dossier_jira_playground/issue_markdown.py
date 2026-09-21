"""A Jira issue payload, read as markdown.

The gap exercise 11 walks into: an issue is held as `application/json`, nothing
installed claims that pair, and R8.5 refuses the whole source rather than
convert half of it. This is the honest fix -- a package that claims the pair --
written the way exercise 03's package is, through the entry-point group and with
no edit to `dossier` (R8.7).

What it decides, and why each decision is a decision:

* **Which fields are the document.** A Jira issue payload is mostly machinery:
  avatars, permission ids, rendered HTML, a `self` URL per nested object. The
  document is the summary, the description, and the handful of fields a person
  reading the incident would want. Everything else is dropped -- and dropping it
  is not tidying, it is what makes a span searchable: `{{documents}}` carrying
  forty kilobytes of avatar URLs is forty kilobytes a model can ground a
  fabricated quote in.
* **A fixed order.** Written in the order below on every machine, never in the
  order the JSON happened to arrive in. Two runs over the same issue must
  produce the same bytes or the convert key means nothing (R8.1, R0.4).
* **No clock, no environment, no network.** The only input is `payload`.

Not shipped with `dossier`, and this file is not a proposal that it should be in
this form -- `resources/proposal.md` is. A converter for a *Jira* issue is not a
converter for `application/json`, and the pair is the whole type: claiming
`application/json` claims every JSON document any source ever holds. That is the
question the proposal asks, and it is why this lives in the playground.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

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
    """`application/json` to the `markdown` kind, for a Jira issue payload."""

    id = "jira-issue-markdown"
    # Every change to what `convert` writes raises this, because the version is
    # in the convert key and an artifact produced by 1.0.0 must never be served
    # for a request that 1.1.0 would answer differently (R5.4, R8.2).
    version = "1.0.0"
    media_type = "application/json"
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
            lines += ["", "## Description", "", description]

        comments = _comments(fields)
        if comments:
            lines += ["", "## Comments", ""]
            for author, body in comments:
                lines += [f"**{author}**", "", body, ""]

        return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _heading(key: str, summary: str) -> str:
    """`# PLAY-1 -- Checkout timeouts ...`, in the corpus notes' own shape.

    The same heading a folder note carries, so a prompt written against one
    reads the other, and a `match` in the stub's reply file tells two issues
    apart on the line a person would use.
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
            f"jira-issue-markdown: the payload is not UTF-8 JSON: {error}"
        ) from None
    if not isinstance(issue, dict):
        raise JiraIssueConversionFailed(
            f"jira-issue-markdown: expected a JSON object, got {type(issue).__name__}"
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
    things whose order carries no meaning (R0.4 is about removing *accidental*
    variation, not about imposing an order on a sequence that has one).
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
            found.append((name or "(unknown)", body))
    return found
