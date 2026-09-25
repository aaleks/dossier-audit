"""A Confluence page as the note a person reads (spec 008, R8.19).

The payload is the JSON Confluence sends for a page rendered for export (R1.17).
Most of it is machinery: `_links`, `_expandable`, and a `self` URL on every
nested object. The note is the page a person reads -- its title, a line each for
the space, the version, when and by whom it was written, then the body -- and
nothing else, for the reason a Jira issue's note is (R8.16).

Which parts, in which order, is decided here. Turning the rendered HTML into
markdown is not: it is a library's work, handed in as `markup` by the converter
that owns it (R8.20), so the decision stays provable without the library.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

# Written in this order, when the page has them. The label is what a reader
# sees; the path is where the value is read from in the payload.
LINES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Space", ("space", "key")),
    ("Version", ("version", "number")),
    ("Updated", ("version", "when")),
    ("By", ("version", "by", "displayName")),
)


def note(payload: bytes, *, markup: Callable[[str], str]) -> str:
    """The note `payload` is, as markdown ending in one newline (R8.19).

    `markup` turns the rendered body into markdown, and is given the body and
    nothing else. A value is written as Confluence sent it: a time is not
    re-zoned, because the note may not depend on the machine converting it
    (R8.1).

    Raises `ValueError` for a payload that is not a rendered page, which R8.6
    isolates to its one document.
    """
    page = _page(payload)
    title = _text(page.get("title")) or _text(page.get("id"))

    written = [f"# {title}", ""]
    for label, path in LINES:
        value = _text(_at(page, path))
        if value:
            written.append(f"**{label}:** {value}")

    body = markup(page["body"]["export_view"]["value"]).strip()
    if body:
        written += ["", body]
    return "\n".join(written).strip() + "\n"


def _page(payload: bytes) -> Mapping[str, object]:
    """The payload as a page: a JSON object holding `body.export_view.value`."""
    try:
        page = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"not a rendered Confluence page: the payload is not UTF-8 JSON ({error})"
        ) from None
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
