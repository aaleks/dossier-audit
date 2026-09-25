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
