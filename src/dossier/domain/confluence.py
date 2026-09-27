"""Decisions the Confluence connector makes about what it holds (spec 001).

Pure: the connector asks, and this answers without a request of its own.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterable


def export_version(page: str | None, files: Iterable[str | None]) -> str | None:
    """The marker of a page's PDF export: the page's, and a digest of its files' (R1.19).

    `v37` for a page carrying no files. Otherwise `v37+` and the first twelve hex
    digits of the SHA-256 of the files' markers, sorted and joined by newlines:
    the PDF draws the page's images, so a file uploaded again in place changes
    the export while the page stays at its version. Sorted, because the order a
    listing comes back in is not something the PDF depends on.

    `None` when the page, or any file, has no marker. An export whose inputs
    cannot all be vouched for cannot be vouched for either, and a made-up
    marker would make R2.1 skip a fetch that was needed (R1.5).
    """
    return _digested(page, files, "+")


def commented_version(page: str | None, comments: Iterable[str | None]) -> str | None:
    """A page's marker with `comments: true`: its own, and a digest of its comments' (R1.24).

    `v37` for a page with no comment. Otherwise `v37+c` and the first twelve
    hex digits of the SHA-256 of its comments' `<id>:v<n>`, sorted and joined by
    newlines. A comment is content of its own, so adding, editing or removing
    one leaves the page at its version; this is what moves instead. Sorted,
    because the order a search answers in is not the page's.

    `None` when the page, or any comment, has no marker, as R1.19's is.
    """
    return _digested(page, comments, "+c")


def including_version(page: str | None, included: Iterable[str | None]) -> str | None:
    """A page's marker when it draws in other pages' text: its own, and theirs (R1.26).

    `v37` for a page including nothing. Otherwise `v37+i` and the first twelve
    hex digits of the SHA-256 of what it includes, each `<id>:v<n>`, or
    `missing:<space>/<title>` for an include naming no page, sorted and joined
    by newlines. An edit to an included page leaves the including one at its
    version and changes what it renders, so this is what moves instead.

    `None` when the page, or anything it includes, has no marker.
    """
    return _digested(page, included, "+i")


def _digested(page: str | None, markers: Iterable[str | None], joint: str) -> str | None:
    """`page`, then `joint` and a digest of `markers` sorted; `page` alone for none."""
    markers = list(markers)
    if page is None or any(marker is None for marker in markers):
        return None
    if not markers:
        return page
    joined = "\n".join(sorted(markers)).encode("utf-8")
    return f"{page}{joint}{hashlib.sha256(joined).hexdigest()[:12]}"


# The macros that draw another page's text into a page (R1.26), as Confluence
# stores them. Each names its page inside it, and nothing else does: a plain link
# to a page is written the same way, outside any such macro.
_INCLUDES = re.compile(
    r'<ac:structured-macro\b[^>]*\bac:name="(?:include|excerpt-include)"[^>]*>(.*?)'
    r"</ac:structured-macro>",
    re.DOTALL,
)
_PAGE = re.compile(r"<ri:page\b([^>]*)/?>")
_ATTRIBUTE = re.compile(r'\b(ri:content-title|ri:space-key)="([^"]*)"')


def included_pages(storage: str, *, space: str) -> list[tuple[str, str]]:
    """The `(space, title)` of each page `storage` includes, sorted (R1.26).

    Read from the storage format, the only place Confluence writes which page an
    `include` or `excerpt-include` names: `<ri:page ri:space-key="OPS"
    ri:content-title="Escalation contacts" />`. A page named without a space is
    in `space`, the including page's own. A title is unescaped as the storage
    escaped it, `&amp;` as `&`.
    """
    named: set[tuple[str, str]] = set()
    for macro in _INCLUDES.finditer(storage):
        for page in _PAGE.finditer(macro.group(1)):
            attributes = dict(_ATTRIBUTE.findall(page.group(1)))
            title = html.unescape(attributes.get("ri:content-title", ""))
            if title:
                named.add((html.unescape(attributes.get("ri:space-key", "")) or space, title))
    return sorted(named)
