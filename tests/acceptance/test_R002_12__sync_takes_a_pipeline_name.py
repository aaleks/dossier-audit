"""R2.12 — `dossier sync <pipeline>` syncs the sources that pipeline declares.

Sync takes a pipeline name, not a configuration path: the pipeline decides what
is worth holding, and it needs both its `sources` and its `reference` sources
held before it can run. A source that `sources.yaml` declares and no pipeline
names is not synced -- the source list says what *can* be fetched, never what
must be.

The fixture folder `incidents-manual` is the audited source. Procedures are a
second source type registered for the test, as an installed package would
register one (R1.7), whose connector counts what it is asked.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from tests.fakes import register_connector
from tests.pipelines import write_pipeline

from dossier.domain.ports import AttachmentRef, ItemRef, RawItem

PIPELINE = "incident-audit"
PAGES = {"OPS-114": "v37", "OPS-115": "v12", "OPS-116": "v3"}


class Procedures:
    """A wiki of procedures, `_fixtures.md`'s `procedures-confluence`. It counts calls."""

    lists_everything = False

    media_type = "text/markdown"

    def __init__(self) -> None:
        self.listed = 0
        self.fetched: list[str] = []

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        self.listed += 1
        for key, version in sorted(PAGES.items()):
            yield ItemRef(key=key, remote_version=version, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        return RawItem(
            key=key,
            payload=f"# {key}\n\nA procedure.\n".encode(),
            media_type=self.media_type,
            remote_version=PAGES[key],
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _with_procedures(workspace: Path, monkeypatch) -> Procedures:
    """`sources.yaml` declaring the fixture folder and the procedures wiki."""
    wiki = Procedures()
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: incidents-manual\n"
        "    type: folder\n"
        "    path: inbox/incidents/\n"
        "  - id: procedures-confluence\n"
        "    type: wiki\n",
        encoding="utf-8",
    )
    register_connector(monkeypatch, "wiki", lambda config, *, workspace: wiki)
    return wiki


def _source_lines(output: str) -> dict[str, str]:
    return {line.split()[0]: line for line in output.splitlines() if " known · " in line}


class TestSyncTakesAPipelineName:
    """R2.12 — `dossier sync <pipeline>` syncs the sources that pipeline declares."""

    def test_the_pipelines_source_is_synced(self, workspace: Path, monkeypatch):
        """Example 1: the one whose pipeline declares `sources: [incidents-manual]`."""
        write_pipeline(workspace, sources=["incidents-manual"])

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert list(_source_lines(result.output)) == ["incidents-manual"]
        assert "-> 3 fetched" in _source_lines(result.output)["incidents-manual"]

    def test_reference_sources_are_synced_too(self, workspace: Path, monkeypatch):
        """Example 2: the one that also declares `reference: [procedures-confluence]`.

        Reference documents are inputs like any other: a pipeline cannot verify
        against a procedure it has not fetched.
        """
        wiki = _with_procedures(workspace, monkeypatch)
        write_pipeline(
            workspace, sources=["incidents-manual"], reference=["procedures-confluence"]
        )

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert sorted(_source_lines(result.output)) == [
            "incidents-manual",
            "procedures-confluence",
        ]
        assert sorted(wiki.fetched) == sorted(PAGES)

    def test_an_unknown_pipeline_is_refused_naming_where_it_looked(
        self, workspace: Path, monkeypatch
    ):
        """Example 3: the one run as `dossier sync no-such-pipeline`.

        Naming where it looked matters more than naming what is missing: the
        usual cause is being in the wrong directory. Nothing is fetched.
        """
        wiki = _with_procedures(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "sync", "no-such-pipeline")

        assert result.exit_code == 2
        assert "no-such-pipeline" in result.output
        assert str(Path("pipelines") / "no-such-pipeline" / "pipeline.yaml") in result.output
        assert wiki.listed == 0 and wiki.fetched == []

    def test_a_source_no_pipeline_names_is_not_synced(self, workspace: Path, monkeypatch):
        """Counter-example (row 4): the one declared in `sources.yaml` and nowhere else.

        Not synced. The pipeline decides what is worth holding, not the source
        list -- a source nobody audits would otherwise be fetched on every sync.
        """
        wiki = _with_procedures(workspace, monkeypatch)
        write_pipeline(workspace, sources=["incidents-manual"])

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert list(_source_lines(result.output)) == ["incidents-manual"]
        assert wiki.listed == 0 and wiki.fetched == []
