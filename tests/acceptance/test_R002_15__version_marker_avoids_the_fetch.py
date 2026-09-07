"""R2.15 — a second sync fetches zero payloads from a source that exposes a version marker.

The other half of the old R2.5. R2.14 took the universal half — nothing is
*stored* twice, whatever the source can tell us — and left this one, which only
holds where the source can vouch that nothing moved.

The split is not pedantry. The cost is different in kind: a Confluence query
answering "still v37" is one request; a folder of 4,000 files is 4,000 reads
however the answer comes out. A rule that blurred the two would let a sync that
reads everything call itself incremental.

No single component can satisfy this. The connector must report a marker it did
not invent (R1.5), the ledger must remember the one it saw last, the domain must
compare them (R2.1), the application must skip the fetch on that answer, and the
CLI must report the count honestly (R2.13). Any one of them shrugging turns
`0 fetched` into a number that means nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import VersionedFolderConnector, register_connector

SOURCE_TYPE = "versioned-folder"
SOURCE_ID = "procedures-confluence"

# The manifest the source vouches for. `OPS-114` is the fixtures' versioned page
# at `v37`; the other two are here so that "the rest are not read" has a rest.
VERSIONS = {"OPS-114": "v37", "OPS-115": "v12", "OPS-116": "v3"}

PAGES = {
    "OPS-114": "# OPS-114\n\nIncident escalation procedure. Exported from Confluence.\n",
    "OPS-115": "# OPS-115\n\nPayment reconciliation runbook.\n",
    "OPS-116": "# OPS-116\n\nLedger batch retention policy.\n",
}

PIPELINE = """\
sources: [procedures-confluence]

model: anthropic:claude-sonnet-4-5-20250929

steps:
  - id: extract
    prompt: prompts/01_extract.md
    input: documents
    mode: per_file
    output: schemas/incident.json
"""

SOURCES = """\
sources:
  - id: procedures-confluence
    type: versioned-folder
    path: inbox/procedures/
"""


@pytest.fixture
def versioned(workspace: Path, monkeypatch) -> VersionedFolderConnector:
    """A workspace whose only source carries version markers.

    The shipped fixture workspace holds a folder source, which by definition has
    no markers (R1.5) and so cannot exercise this rule at all. Rather than adding
    a second source to `tests/fixtures/` — where it would change what every other
    acceptance test syncs — the versioned source is built here and the pipeline is
    pointed at it alone, so the reported counts belong to exactly one source.
    """
    root = workspace / "inbox" / "procedures"
    root.mkdir(parents=True)
    for key, text in PAGES.items():
        (root / f"{key}.md").write_text(text, encoding="utf-8")

    manifest = workspace / f"{SOURCE_ID}.versions.json"
    manifest.write_text(json.dumps(VERSIONS, indent=2), encoding="utf-8")

    (workspace / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    (workspace / "pipelines" / "incident-audit" / "pipeline.yaml").write_text(
        PIPELINE, encoding="utf-8"
    )

    connector = VersionedFolderConnector(root, manifest)
    # One instance across both runs, so a test can clear `fetched` in between and
    # read the second run's count on its own.
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: connector)
    return connector


def _run_sync(workspace: Path, monkeypatch, pipeline: str = "incident-audit"):
    """Invoke `dossier sync <pipeline>` with the workspace as the cwd (R0.8, R2.12)."""
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    result = CliRunner().invoke(app, ["sync", pipeline])
    assert result.exit_code == 0, result.output
    return result


def _set_version(workspace: Path, key: str, version: str) -> None:
    """Move one item's marker, as the source would when the page is edited."""
    manifest = workspace / f"{SOURCE_ID}.versions.json"
    versions = json.loads(manifest.read_text(encoding="utf-8"))
    versions[key] = version
    manifest.write_text(json.dumps(versions, indent=2), encoding="utf-8")


def _snapshot_bytes(workspace: Path) -> set[bytes]:
    store = workspace / ".dossier" / "snapshots"
    return {path.read_bytes() for path in store.rglob("*") if path.is_file()}


class TestAVersionMarkerAvoidsTheFetch:
    """R2.15 — where the source can vouch that nothing moved, we take its word."""

    def test_a_second_sync_of_an_unchanged_source_fetches_nothing(
        self, workspace: Path, monkeypatch, versioned: VersionedFolderConnector
    ):
        """Example 1: the one where the markers answer the question outright."""
        _run_sync(workspace, monkeypatch)
        assert versioned.fetch_count == 3, "the first run has no ledger and must read"

        versioned.fetched.clear()
        second = _run_sync(workspace, monkeypatch)

        assert versioned.fetched == []
        assert "0 fetched" in second.output

    def test_only_the_item_whose_marker_moved_is_read(
        self, workspace: Path, monkeypatch, versioned: VersionedFolderConnector
    ):
        """Example 2: the one where `OPS-114` goes v37 -> v38 and the rest do not.

        A count alone would be satisfied by reading the wrong single item, so this
        asserts *which* key was read.
        """
        _run_sync(workspace, monkeypatch)
        versioned.fetched.clear()

        _set_version(workspace, "OPS-114", "v38")
        (workspace / "inbox" / "procedures" / "OPS-114.md").write_text(
            PAGES["OPS-114"] + "\nEscalation window shortened to 30 minutes.\n",
            encoding="utf-8",
        )

        second = _run_sync(workspace, monkeypatch)

        assert versioned.fetched == ["OPS-114"]
        assert "1 fetched" in second.output
        assert "1 new snapshots" in second.output

    def test_a_source_without_markers_reads_on_every_run_and_says_so(
        self, workspace: Path, monkeypatch
    ):
        """Example 3: the one where the folder source is honest about the cost.

        Deliberately not using the `versioned` fixture — this is the unmodified
        workspace, whose folder source has no markers (R1.5). Reporting
        `0 fetched` here would be a lie, and the rule names that as the failure it
        is guarding against.
        """
        _run_sync(workspace, monkeypatch)
        second = _run_sync(workspace, monkeypatch)

        assert "3 fetched" in second.output
        assert "0 fetched" not in second.output
        assert "0 new snapshots" in second.output

    def test_an_edit_behind_the_marker_is_not_detected(
        self, workspace: Path, monkeypatch, versioned: VersionedFolderConnector
    ):
        """Counter-example (row 4): the one that states the price of trusting a marker.

        `OPS-115` is edited while its version stays `v12`. Nothing is read, so
        nothing is stored, and the store still holds the superseded text. That is
        not a defect to be fixed here — it is the cost of R2.15, and it is why R1.5
        forbids a connector from inventing a marker it cannot stand behind.
        Asserting it keeps the trade-off visible rather than surprising.
        """
        _run_sync(workspace, monkeypatch)
        versioned.fetched.clear()
        stored_after_first = _snapshot_bytes(workspace)

        edited = workspace / "inbox" / "procedures" / "OPS-115.md"
        edited.write_text(PAGES["OPS-115"] + "\nSuperseded 2026-08-07.\n", encoding="utf-8")

        second = _run_sync(workspace, monkeypatch)

        assert versioned.fetched == []
        assert "0 fetched" in second.output
        assert "0 new snapshots" in second.output
        assert _snapshot_bytes(workspace) == stored_after_first
        assert edited.read_bytes() not in _snapshot_bytes(workspace), (
            "the edit is invisible to dossier, and the rule says so out loud"
        )
