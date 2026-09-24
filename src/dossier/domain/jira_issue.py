"""A Jira issue as the note a person reads (spec 008, R8.16).

An issue payload is mostly machinery: avatar URLs, a `self` link on every nested
object, permission ids, a hundred custom fields that are empty. The note is what
a person reading the incident reads -- the key and summary, a few fields, the
description and the comments -- in that order, and nothing else. Dropping the
rest is not tidying: forty kilobytes of avatar URLs in `{{documents}}` is forty
kilobytes a model can find a plausible quote in.

Which fields, in which order, is decided here. Turning wiki markup into markdown
is not: it is a library's work, handed in as `markup` by the converter that owns
it (R8.17), so the decision stays provable without the library.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

# Written in this order, when the issue has them. The label is what a reader
# sees; the path is where the value is read from under `fields`.
FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Status", ("status", "name")),
    ("Type", ("issuetype", "name")),
    ("Priority", ("priority", "name")),
    ("Resolution", ("resolution", "name")),
    ("Created", ("created",)),
    ("Updated", ("updated",)),
)

# Who wrote a comment, when Jira did not say.
NO_AUTHOR = "(unknown)"


def note(payload: bytes, *, markup: Callable[[str], str]) -> str:
    """The note `payload` is, as markdown ending in one newline (R8.16).

    `markup` turns Jira wiki markup into markdown, and is given the description
    and each comment's body and nothing else. The summary and the fields are
    shown by Jira as typed, so they are written as typed (R8.17 row 4). A value
    is written as Jira sent it: a timestamp is not re-zoned, because the note may
    not depend on the machine converting it (R8.1).

    Raises `ValueError` for a payload that is not an issue, which R8.6 isolates
    to its one document.
    """
    issue = _issue(payload)
    fields = issue["fields"]

    written = [_heading(str(issue.get("key") or ""), _text(fields.get("summary"))), ""]
    for label, path in FIELDS:
        value = _at(fields, path)
        if value:
            written.append(f"**{label}:** {value}")

    attachments = [
        _text(attachment.get("filename"))
        for attachment in _objects(fields.get("attachment"))
        if _text(attachment.get("filename"))
    ]
    if attachments:
        # Named, never inlined. Each is its own document with its own key and
        # snapshot (R1.6); its text here as well would put one sentence in two
        # artifacts, and a span found in it could not say which.
        written.append(f"**Attachments:** {', '.join(attachments)}")

    description = _text(fields.get("description"))
    if description:
        written += ["", "## Description", "", markup(description).strip()]

    thread = fields.get("comment")
    if isinstance(thread, Mapping):
        written += _comments(thread, markup=markup)

    return "\n".join(written).strip() + "\n"


def _issue(payload: bytes) -> Mapping[str, object]:
    """The payload as an issue: a JSON object with a `fields` object in it."""
    try:
        issue = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"not a Jira issue: the payload is not UTF-8 JSON ({error})") from None
    if not isinstance(issue, dict) or not isinstance(issue.get("fields"), dict):
        # Refused here, by name, rather than four fields further on with an
        # `AttributeError` that says nothing about which document it was.
        raise ValueError("not a Jira issue: the payload has no `fields` object")
    return issue


def _heading(key: str, summary: str) -> str:
    """`# INC-4821 — Card payments declined at checkout`, the issue as it is named."""
    return f"# {' — '.join(part for part in (key.strip(), summary) if part)}"


def _comments(thread: Mapping[str, object], *, markup: Callable[[str], str]) -> list[str]:
    """Each comment under its author and time, in the order Jira returned them.

    Jira's order is the thread's order. Sorting it would make a different
    conversation: R0.4 removes accidental variation, and this order is not an
    accident.
    """
    comments = _objects(thread.get("comments"))
    if not comments:
        return []
    written = ["", "## Comments"]
    for comment in comments:
        author = comment.get("author")
        name = ""
        if isinstance(author, Mapping):
            name = _text(author.get("displayName")) or _text(author.get("name"))
        created = _text(comment.get("created"))
        heading = f"**{name or NO_AUTHOR}**" + (f" · {created}" if created else "")
        written += ["", heading, "", markup(_text(comment.get("body"))).strip()]
    return written


def _objects(value: object) -> list[Mapping[str, object]]:
    """The objects in a JSON list, or none; anything else in it is not an entry."""
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [entry for entry in value if isinstance(entry, Mapping)]


def _at(fields: Mapping[str, object], path: tuple[str, ...]) -> str:
    """`("status", "name")` as `fields["status"]["name"]`, or "" at the first miss."""
    current: object = fields
    for step in path:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(step)
    return _text(current)


def _text(value: object) -> str:
    """A value as the text it shows, or "" for one that is absent."""
    return "" if value is None else str(value).strip()
