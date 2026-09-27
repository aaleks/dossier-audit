"""A Jira issue as the note a person reads (spec 008, R8.16, R8.18, R8.31).

An issue payload is mostly machinery: avatar URLs, a `self` link on every nested
object, permission ids, a hundred custom fields that are empty. The note is what
a person reading the incident reads -- the key and summary, a few fields, the
custom fields that hold something a person reads, the description and the
comments -- in that order, and nothing else. Dropping the rest is not tidying:
forty kilobytes of avatar URLs in `{{documents}}` is forty kilobytes a model can
find a plausible quote in.

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

# How Jira spells a custom field's id, in `fields`, `names` and `schema` alike.
CUSTOM = "customfield_"

# The `schema` types of a custom field a person reads, alone or as an `array` of
# them (R8.31). Jira Software declares its own machinery -- `Development`,
# `Rank` -- as `any`, and a type that is not here is not written.
READABLE = frozenset(
    {"string", "number", "date", "datetime", "option", "option-with-child", "user", "version"}
)

# `Sprint` is an array of strings, which a person would read, and Data Center
# fills each with a Java object's dump. It is left out by what it is (R8.31).
SPRINT = "com.pyxis.greenhopper.jira:gh-sprint"


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
    written += _custom_fields(issue, fields)

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


def _custom_fields(issue: Mapping[str, object], fields: Mapping[str, object]) -> list[str]:
    """`**<name>:** <value>` for each custom field a person reads, by name, then id (R8.31).

    The name is the one Jira gives it in `names`, and whether a person reads it
    is its type in `schema`; both are in the payload only when the fetch asked
    (R1.28). A payload held before has neither, and so no custom field: its note
    is the one it had. Two fields may share a name, so the id orders them.
    """
    names, schemas = issue.get("names"), issue.get("schema")
    if not isinstance(names, Mapping) or not isinstance(schemas, Mapping):
        return []
    written: list[tuple[str, str, str]] = []
    for field, value in fields.items():
        name, schema = _text(names.get(field)), schemas.get(field)
        if not field.startswith(CUSTOM) or not name or not isinstance(schema, Mapping):
            continue
        shown = _custom_value(value, schema)
        if shown:
            written.append((name, field, f"**{name}:** {shown}"))
    return [line for _, _, line in sorted(written)]


def _custom_value(value: object, schema: Mapping[str, object]) -> str:
    """A custom field's value as the note writes it, or "" when it is not written.

    An `array` is its items, each written as its `items` type says, joined by
    `, `; an item that writes as nothing is skipped.
    """
    if schema.get("custom") == SPRINT:
        return ""
    kind, items = schema.get("type"), schema.get("items")
    if kind == "array":
        if not _readable(items) or not isinstance(value, Sequence) or isinstance(value, str):
            return ""
        return ", ".join(
            shown for shown in (_shown(item, str(items)) for item in value) if shown
        )
    return _shown(value, str(kind)) if _readable(kind) else ""


def _readable(kind: object) -> bool:
    """Whether `kind`, a `schema` type, is one a person reads."""
    return isinstance(kind, str) and kind in READABLE


def _shown(value: object, kind: str) -> str:
    """One value of a readable type, as R8.31 writes it, or "" for none.

    An option as its `value`, and with a child as `<value> - <child's value>`;
    a user as their display name; a version as its name; a string, number, date
    or time as sent.
    """
    if kind in ("option", "option-with-child"):
        if not isinstance(value, Mapping):
            return ""
        shown, child = _text(value.get("value")), value.get("child")
        below = _text(child.get("value")) if isinstance(child, Mapping) else ""
        return (
            f"{shown} - {below}" if kind == "option-with-child" and shown and below else shown
        )
    if kind == "user":
        if not isinstance(value, Mapping):
            return ""
        return _text(value.get("displayName")) or _text(value.get("name"))
    if kind == "version":
        return _text(value.get("name")) if isinstance(value, Mapping) else ""
    # A scalar, as sent. An object or a list where one was declared is not a
    # value a person reads, and `true` is not a number.
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return ""
    return _text(value)


def _comments(thread: Mapping[str, object], *, markup: Callable[[str], str]) -> list[str]:
    """Each comment under its author and time, in the order Jira returned them.

    Jira's order is the thread's order. Sorting it would make a different
    conversation: R0.4 removes accidental variation, and this order is not an
    accident.
    """
    comments = _objects(thread.get("comments"))
    total = thread.get("total")
    # Only a count Jira sent as a number is read as one. `bool` is an `int` to
    # Python, and `true` is not a number of comments.
    counted = total if isinstance(total, int) and not isinstance(total, bool) else len(comments)
    missing = counted - len(comments)
    if not comments and missing <= 0:
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
    if missing > 0:
        # Said, rather than left for a stage to assume the thread is whole: a
        # conclusion read from the first half of a thread is a different one
        # (R8.18).
        written += ["", f"{missing} of {counted} comments are not in this snapshot."]
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
