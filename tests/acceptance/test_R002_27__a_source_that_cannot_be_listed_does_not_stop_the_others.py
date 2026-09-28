"""R2.27, at the CLI — a source whose listing fails does not stop the sources after it.

`vendor-docs`, the website of `specs/_fixtures.md`, is synced before
`incidents-manual`, the fixture folder. Its sitemap answers `503`. Before this
rule, `dossier sync` ended there in a traceback and the folder was never synced;
`www.python.org/about/` with `crawl: 5` did that on 2026-09-28. Now the command
names the source and the reason, syncs the folder, and exits `1`.

The website is `tests.docs_site`, served with no socket.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from tests.docs_site import SITEMAP, URL, DocsSite
from tests.fakes import FakeTracker, register_connector
from tests.pipelines import write_pipeline

from dossier.infrastructure.connectors.web import WebConnector, WebKeys

PIPELINE = "incident-audit"
URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _sources(workspace: Path, monkeypatch, site: DocsSite) -> None:
    """`vendor-docs`, served by `site`, and then the fixture folder."""
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: vendor-docs\n"
        "    type: docs-site\n"
        f"    url: {URL}\n"
        "  - id: incidents-manual\n"
        "    type: folder\n"
        "    path: inbox/incidents/\n",
        encoding="utf-8",
    )
    register_connector(
        monkeypatch,
        "docs-site",
        lambda config, *, workspace: WebConnector(url=URL, transport=site.transport()),
        keys=WebKeys,
    )
    write_pipeline(workspace, sources=["vendor-docs", "incidents-manual"])


def _unreadable() -> DocsSite:
    return DocsSite(responses={SITEMAP: httpx.Response(503)})


class TestASourceThatCannotBeListedDoesNotStopTheOthers:
    """R2.27 — the failure is named, and the next source syncs."""

    def test_the_failure_is_named_and_the_next_source_syncs(self, workspace: Path, monkeypatch):
        """Example 1: the one where `vendor-docs`' sitemap answers `503`."""
        _sources(workspace, monkeypatch, _unreadable())

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 1, result.output
        assert "vendor-docs: listing failed:" in result.output
        assert SITEMAP in result.output and "503" in result.output
        assert any(line.startswith("incidents-manual ") for line in result.output.splitlines())
        assert "Traceback" not in result.output

    def test_a_tracked_sync_ends_failed(self, workspace: Path, monkeypatch):
        """Example 5: the one where the record says what the terminal said."""
        import dossier.cli.bootstrap as cli

        _sources(workspace, monkeypatch, _unreadable())
        recorder = FakeTracker()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 1, result.output
        [run] = recorder.runs
        assert run.status == "FAILED"
