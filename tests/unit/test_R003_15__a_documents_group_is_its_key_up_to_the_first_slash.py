"""R3.15 — a document's group is its key up to the first `/`.

The decision half of R3.15, and the reason `per_group` needs no configuration:
every connector already keys a file under what it belongs to. A Jira attachment
is `INC-4821/report.pdf` (R1.6), a Confluence file `81920114/escalation-matrix.png`
(R1.18), a folder's file its path under the folder. So the group is read off the
key, and a replay recomposes it from the keys its manifest pins (R4.15).

The CLI half -- one call per group -- is the acceptance test's.
"""

from __future__ import annotations

import pytest


def _group_of(key: str) -> str:
    from dossier.domain.groups import group_of

    return group_of(key)


class TestADocumentsGroupIsItsKeyUpToTheFirstSlash:
    """R3.15 — the group is the first segment of the key."""

    @pytest.mark.parametrize(
        ("key", "group"),
        [
            # Row 1: the one where a contract is a folder of files.
            ("ACME-2024/amendment-3.pdf", "ACME-2024"),
            # Row 3: the one where an attachment is filed under its issue, and
            # the issue itself -- a key with no `/` -- is the same group.
            ("INC-4821/report.pdf", "INC-4821"),
            ("INC-4821", "INC-4821"),
            # Row 5: the one where the folder goes two levels deep. The first
            # segment, not the last directory: an amendments/ subfolder is still
            # the contract's.
            ("ACME-2024/amendments/amendment-3.pdf", "ACME-2024"),
        ],
    )
    def test_the_group_is_the_key_up_to_its_first_slash(self, key: str, group: str):
        assert _group_of(key) == group

    def test_a_key_with_no_slash_is_a_group_of_its_own(self):
        """Row 8, a counter-example: the one with nothing to group.

        A flat folder is a folder of groups of one, each named by its key, so
        `per_group` over it asks exactly what `per_file` asks.
        """
        assert _group_of("PLAY-1001.md") == "PLAY-1001.md"

    def test_a_pages_pdf_export_is_not_the_pages_group(self):
        """Row 9, a counter-example: the one with a dot where a slash would be.

        Confluence keys a page's PDF export `81920114.pdf` (R1.19). Nothing in
        the key says it belongs to page `81920114`, and guessing from a file
        extension would be a second grouping rule nobody agreed (spec 003, open
        question 1).
        """
        assert _group_of("81920114.pdf") == "81920114.pdf"
        assert _group_of("81920114/escalation-matrix.png") == "81920114"
