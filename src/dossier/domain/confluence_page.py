"""A Confluence page as the note a person reads (spec 008, R8.19, R8.30).

The payload is the JSON Confluence sends for a page rendered for export (R1.17),
or, from a source with `comments: true`, that and its comments as Confluence
sent them: `{"page":…,"comments":[…]}` (R1.23). Most of it is machinery:
`_links`, `_expandable`, and a `self` URL on every nested object. The note is
the page a person reads -- its title, a line each for the space, the version,
when and by whom it was written, then the body, then any comments -- and nothing
else, for the reason a Jira issue's note is (R8.16).

Which parts, in which order, is decided here. Turning the rendered HTML into
markdown is not: it is a library's work, handed in as `markup` by the converter
that owns it (R8.20), so the decision stays provable without the library.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

# Written in this order, when the page has them. The label is what a reader
# sees; the path is where the value is read from in the payload.
LINES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Space", ("space", "key")),
    ("Version", ("version", "number")),
    ("Updated", ("version", "when")),
    ("By", ("version", "by", "displayName")),
)

# Who wrote a comment, when Confluence did not say.
NO_AUTHOR = "(unknown)"


def note(payload: bytes, *, markup: Callable[[str], str]) -> str:
    """The note `payload` is, as markdown ending in one newline (R8.19, R8.30).

    `markup` turns rendered HTML into markdown, and is given the body and each
    comment's body and nothing else. A value is written as Confluence sent it: a
    time is not re-zoned, because the note may not depend on the machine
    converting it (R8.1).

    Raises `ValueError` for a payload that is not a rendered page, which R8.6
    isolates to its one document.
    """
    held = _held(payload)
    page = _page(held)
    title = _text(page.get("title")) or _text(page.get("id"))

    written = [f"# {title}", ""]
    for label, path in LINES:
        value = _text(_at(page, path))
        if value:
            written.append(f"**{label}:** {value}")

    body = markup(page["body"]["export_view"]["value"]).strip()
    if body:
        written += ["", body]
    written += _comments(held, markup=markup)
    return "\n".join(written).strip() + "\n"


def _held(payload: bytes) -> Mapping[str, object]:
    """The payload as JSON: a page, or a page and its comments (R1.23)."""
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"not a rendered Confluence page: the payload is not UTF-8 JSON ({error})"
        ) from None


def _comments(held: Mapping[str, object], *, markup: Callable[[str], str]) -> list[str]:
    """Each comment under its author and time, in the order Confluence answered (R8.30).

    `depth=all` answers in the thread's order: a comment, its replies, then the
    next. Sorting it would make a different conversation, as R8.16 says of
    Jira's. A reply names its parent only by id, among its `ancestors`, the
    nearest last; the parent is in the same answers, so its author is found
    there.
    """
    if not isinstance(held, Mapping) or "page" not in held:
        return []
    comments = [
        comment
        for answer in _objects(held.get("comments"))
        for comment in _objects(answer.get("results"))
    ]
    if not comments:
        return []
    authors = {_text(comment.get("id")): _author(comment) for comment in comments}
    written = ["", "## Comments"]
    for comment in comments:
        heading = f"**{_author(comment)}**"
        created = _text(_at(comment, ("history", "createdDate")))
        if created:
            heading += f" · {created}"
        parents = _objects(comment.get("ancestors"))
        if parents:
            heading += f" · reply to {authors.get(_text(parents[-1].get('id')), NO_AUTHOR)}"
        text = markup(_text(_at(comment, ("body", "export_view", "value")))).strip()
        written += ["", heading, "", text]
    return written


def _author(comment: Mapping[str, object]) -> str:
    return (
        _text(_at(comment, ("history", "createdBy", "displayName")))
        or _text(_at(comment, ("history", "createdBy", "username")))
        or NO_AUTHOR
    )


def _objects(value: object) -> list[Mapping[str, object]]:
    """The objects in a JSON list, or none; anything else in it is not an entry."""
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [entry for entry in value if isinstance(entry, Mapping)]


def _page(held: object) -> Mapping[str, object]:
    """The page held: a JSON object holding `body.export_view.value`.

    Held with its comments, it is the envelope's `page` (R1.23). An envelope
    with no `page` is looked at as a page, and refused as one.
    """
    page = held.get("page") if isinstance(held, Mapping) and "page" in held else held
    if not isinstance(_at(page, ("body", "export_view", "value")), str):
        # Refused here, by name, rather than a `KeyError` further on that says
        # nothing about which document it was.
        raise ValueError(
            "not a rendered Confluence page: the payload has no `body.export_view`"
        )
    return page


def _at(value: object, path: tuple[str, ...]) -> object:
    for part in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _text(value: object) -> str:
    """A value as the note writes it: a string or a number as sent, anything else as nothing."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, str | int | float):
        return str(value).strip()
    return ""
