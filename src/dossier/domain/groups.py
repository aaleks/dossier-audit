"""Which group a document belongs to, for a `per_group` step (R3.15).

A supplier contract is a master agreement and its amendments, and no single
file answers a question about it (`docs/second-use-case.md`, finding 1). A group
is read off the key rather than configured, because every connector already
files a document under what it belongs to: a Jira attachment is
`INC-4821/report.pdf` (R1.6), a Confluence file `81920114/escalation-matrix.png`
(R1.18), a folder's file its path under the folder. And a key is what a manifest
pins, so a replay recomposes the groups a run asked about from the manifest
alone (R4.15).
"""

from __future__ import annotations

SEPARATOR = "/"


def group_of(key: str) -> str:
    """The group `key` belongs to: the key up to its first `/`, or the key itself.

    The first segment, not the last directory: `ACME-2024/amendments/amendment-3.pdf`
    is still the contract's. A key with no `/` is a group of one, named by the
    key, so `per_group` over a flat folder asks what `per_file` asks. Nothing
    else in a key is read: `81920114.pdf`, a page's PDF export, is not guessed
    into page `81920114`'s group from its extension (spec 003, open question 1).
    """
    return key.split(SEPARATOR, 1)[0]
