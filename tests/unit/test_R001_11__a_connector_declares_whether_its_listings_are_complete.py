"""R1.11 — a connector declares whether every listing it returns is complete.

Tombstoning is held minus listed, safe only against a listing that omitted
nothing. Sync can see that a listing asked for with `since=None` is complete;
it cannot see that a connector would have returned everything anyway. The
folder did exactly that on every sync, and a deleted file stayed `active` for
ever because the interface gave it no way to say so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dossier.infrastructure.connectors.folder import FolderConnector
from dossier.infrastructure.connectors.jira import JiraConnector

WINDOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)


class TestAConnectorDeclaresWhetherItsListingsAreComplete:
    """R1.11 — `lists_everything` is a fact about the type, not about one call."""

    def test_the_folder_returns_everything_whatever_it_is_asked(self, tmp_path: Path):
        """Example 1: the one where the folder has no window to narrow by."""
        for name in ("INC-4821.md", "INC-4822.md", "audit-note.pdf"):
            (tmp_path / name).write_bytes(b"content of " + name.encode())
        connector = FolderConnector(tmp_path)

        assert connector.lists_everything is True
        assert list(connector.list(WINDOW)) == list(connector.list(None))
        assert len(list(connector.list(WINDOW))) == 3

    def test_jira_narrows_its_query_by_since(self):
        """Example 2: the one where `since` becomes a JQL clause."""
        connector = JiraConnector(base_url="https://jira.example", query="project = INC")

        assert connector.lists_everything is False
