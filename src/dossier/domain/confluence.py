"""Decisions the Confluence connector makes about what it holds (spec 001).

Pure: the connector asks, and this answers without a request of its own.
"""

from __future__ import annotations

import hashlib
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
    markers = list(files)
    if page is None or any(marker is None for marker in markers):
        return None
    if not markers:
        return page
    joined = "\n".join(sorted(markers)).encode("utf-8")
    return f"{page}+{hashlib.sha256(joined).hexdigest()[:12]}"


def commented_version(page: str | None, comments: Iterable[str | None]) -> str | None:
    """A page's marker with `comments: true`: its own, and a digest of its comments' (R1.24).

    `v37` for a page with no comment. Otherwise `v37+c` and the first twelve
    hex digits of the SHA-256 of its comments' `<id>:v<n>`, sorted and joined by
    newlines. A comment is content of its own, so adding, editing or removing
    one leaves the page at its version; this is what moves instead. Sorted,
    because the order a search answers in is not the page's.

    `None` when the page, or any comment, has no marker, as R1.19's is.
    """
    markers = list(comments)
    if page is None or any(marker is None for marker in markers):
        return None
    if not markers:
        return page
    joined = "\n".join(sorted(markers)).encode("utf-8")
    return f"{page}+c{hashlib.sha256(joined).hexdigest()[:12]}"
