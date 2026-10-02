"""R0.18 — a `dossier` whose installed entry points are not the ones its source
declares stops before any work, saying to reinstall.

Connectors, converters and providers are found by entry point, and those come
from the metadata written at install time, not from `pyproject.toml`. An install
older than an entry point cannot find it, and fails confusingly on whatever
needed it. Here the comparison is a pure decision, and the command and the test
suite are shown refusing an install that is missing one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli

from dossier.domain.install import stale_entry_points, stale_install_line

DECLARED = {
    "dossier.embeddings": {
        "ollama": "dossier.infrastructure.models.ollama_embed:ollama_embeddings"
    },
    "dossier.models": {"ollama": "dossier.infrastructure.models.ollama:ollama"},
}
BEFORE_EMBEDDINGS = {
    "dossier.models": {"ollama": "dossier.infrastructure.models.ollama:ollama"}
}
STALE = (
    "dossier is installed from older metadata than its source: dossier.embeddings ollama "
    "is declared and not installed. Reinstall it: uv sync"
)


class TestAStaleInstallIsRefused:
    """R0.18 — what the source declares, against what is installed."""

    def test_an_entry_point_declared_and_not_installed_is_named(self):
        """Row 1 — the one installed before `dossier.embeddings` `ollama` was declared."""
        found = stale_entry_points(declared=DECLARED, installed=BEFORE_EMBEDDINGS)

        assert stale_install_line(found) == STALE

    def test_an_entry_point_removed_or_moved_is_named(self):
        """Row 3 — the ones installed and no longer declared, and declared elsewhere."""
        moved = {
            "dossier.embeddings": {"ollama": "dossier.old:embeddings"},
            "dossier.models": {"ollama": "dossier.infrastructure.models.ollama:ollama"},
            "dossier.chunkers": {"headings": "dossier.domain.chunks:HeadingsChunker"},
        }

        assert stale_entry_points(declared=DECLARED, installed=moved) == [
            "dossier.chunkers headings is installed and no longer declared",
            "dossier.embeddings ollama is declared as "
            "dossier.infrastructure.models.ollama_embed:ollama_embeddings, "
            "installed as dossier.old:embeddings",
        ]

    def test_the_same_entry_points_say_nothing(self):
        """Row 5, counter-example — the one installed from the source as it is."""
        assert stale_entry_points(declared=DECLARED, installed=DECLARED) == []

    def test_this_checkout_is_installed_from_its_source(self):
        """Row 5, counter-example — the install this suite runs on, which `conftest` checked."""
        from dossier.cli.bootstrap import stale_install

        assert stale_install() is None


class TestThroughTheCommandAndTheSuite:
    """R0.18 — every command, and the test suite, stop before any work."""

    def test_a_command_stops_before_any_work(self, workspace: Path, monkeypatch):
        """Row 1 — `dossier status`, in an empty workspace it never reads."""
        import dossier.cli.bootstrap as cli

        monkeypatch.setattr(cli, "declared_entry_points", lambda: DECLARED)
        monkeypatch.setattr(cli, "installed_entry_points", lambda: BEFORE_EMBEDDINGS)

        result = _cli(workspace, monkeypatch, "status")

        assert result.exit_code == 2, result.output
        assert result.stderr.splitlines() == [STALE]

    def test_the_test_suite_stops_before_any_test(self, monkeypatch):
        """Row 2 — the session start `conftest` runs, against the same install."""
        from tests.conftest import pytest_sessionstart

        import dossier.cli.bootstrap as cli

        monkeypatch.setattr(cli, "declared_entry_points", lambda: DECLARED)
        monkeypatch.setattr(cli, "installed_entry_points", lambda: BEFORE_EMBEDDINGS)

        with pytest.raises(pytest.exit.Exception) as stopped:
            pytest_sessionstart(None)

        assert str(stopped.value) == STALE

    def test_an_install_with_no_source_beside_it_is_not_checked(self, monkeypatch):
        """Row 4, counter-example — a wheel, which has no `pyproject.toml` of `dossier`."""
        import dossier.cli.bootstrap as cli

        monkeypatch.setattr(cli, "declared_entry_points", lambda: None)
        monkeypatch.setattr(cli, "installed_entry_points", lambda: BEFORE_EMBEDDINGS)

        assert cli.stale_install() is None
