"""R8.8 — `dossier convert` reports what it converted, per source and in total.

The counts are the interface, as they are for sync (R2.13). A conversion that
says nothing is indistinguishable from one that was served entirely from cache,
and the whole claim of an incremental pipeline is that you can see what it did.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PIPELINE = "incident-audit"


def _run(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """A workspace whose three fixture documents are held but not converted."""
    result = _run(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return workspace


class TestConvertReportsWhatItDid:
    """R8.8 — held, converted, cached, per source."""

    def test_a_first_conversion_reports_every_document_as_work(
        self, synced: Path, monkeypatch
    ):
        """Example 1: the one where nothing is cached yet."""
        result = _run(synced, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "incidents-manual" in result.output
        assert "3 held" in result.output
        assert "3 converted" in result.output
        assert "0 cached" in result.output

    def test_a_second_conversion_reports_cache_hits_and_writes_nothing(
        self, synced: Path, monkeypatch
    ):
        """Example 2: the one where the work was already paid for.

        Asserted on the cache directory as well as the counts. "0 converted" and
        "nothing was written" are different claims, and a conversion that
        rewrote identical bytes would satisfy the first while breaking the second.
        """
        _run(synced, monkeypatch, "convert", PIPELINE)
        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted((synced / ".dossier" / "cache").rglob("*"))
            if path.is_file()
        }

        second = _run(synced, monkeypatch, "convert", PIPELINE)

        assert "0 converted" in second.output
        assert "3 cached" in second.output
        assert {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted((synced / ".dossier" / "cache").rglob("*"))
            if path.is_file()
        } == before

    def test_raising_a_converter_version_reconverts_everything(
        self, synced: Path, monkeypatch
    ):
        """Example 3: the one where the version is part of the key (R5.4).

        The improvement is simulated by raising the version, which is exactly
        what a converter author does. Every key moves, so every document
        re-converts and nothing is served from cache.
        """
        from dossier.infrastructure.converters.markdown_text import MarkdownTextConverter

        _run(synced, monkeypatch, "convert", PIPELINE)
        monkeypatch.setattr(MarkdownTextConverter, "version", "1.1.0")

        after = _run(synced, monkeypatch, "convert", PIPELINE)

        assert "3 converted" in after.output
        assert "0 cached" in after.output

    def test_the_old_artifacts_are_still_there_afterwards(self, synced: Path, monkeypatch):
        """The one where re-converting adds rather than replaces.

        A raised version must not delete what the old version produced: a run
        pinned to the old artifacts still has to replay (R4.9), and the cache is
        addressed by key precisely so both can exist.
        """
        from dossier.infrastructure.converters.markdown_text import MarkdownTextConverter

        _run(synced, monkeypatch, "convert", PIPELINE)
        first = {
            path.name for path in (synced / ".dossier" / "cache").rglob("*") if path.is_file()
        }

        monkeypatch.setattr(MarkdownTextConverter, "version", "1.1.0")
        _run(synced, monkeypatch, "convert", PIPELINE)

        after = {
            path.name for path in (synced / ".dossier" / "cache").rglob("*") if path.is_file()
        }
        assert first < after
        assert len(after) == 6

    def test_a_source_whose_documents_all_fail_says_so_and_exits_non_zero(
        self, synced: Path, monkeypatch
    ):
        """Counter-example (row 4): the one where a failure is not zero work.

        Reported with reasons and excluded from the converted count. A run that
        printed `0 converted` and exited zero would be indistinguishable from a
        run that had nothing to do (R8.6, R1.9's shape).
        """
        from dossier.infrastructure.converters.markdown_text import MarkdownTextConverter

        def explode(self, payload: bytes, options) -> bytes:
            raise ValueError("unexpected end of file")

        monkeypatch.setattr(MarkdownTextConverter, "convert", explode)

        result = _run(synced, monkeypatch, "convert", PIPELINE)

        assert result.exit_code != 0
        assert "0 converted" in result.output
        assert "3 failed" in result.output
        assert "unexpected end of file" in result.output

    def test_an_unclaimed_media_type_stops_the_command(self, synced: Path, monkeypatch):
        """The CLI half of R8.5: a configuration error, not a per-document one.

        The message has to survive the trip through the CLI intact -- naming the
        document, the type and the entry point group -- because that is where a
        person actually reads it.
        """
        import dossier.infrastructure.converters.registry as registry

        monkeypatch.setattr(registry, "entry_points", lambda group: [])

        result = _run(synced, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 2
        assert "text/markdown" in result.output
        assert "dossier.converters" in result.output
