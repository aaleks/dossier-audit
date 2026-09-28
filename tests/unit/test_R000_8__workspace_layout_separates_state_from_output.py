"""R0.8 — generated state lives under `.dossier/`, and run outputs under `runs/`.

Machine-local state is derived, large and regenerable; run outputs are read by
people. The two are kept apart so that deleting the first is always safe, which
is the claim row 3 actually measures: delete `.dossier/`, sync again, run again,
and the bytes come back.

The workspace is the fixture folder source, synced through the real CLI. The run
goes through `execute`, which is what the CLI calls once it has resolved its
arguments -- where a manifest is written is this layer's decision, and the
decision is what the rule is about.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for, write_pipeline

from dossier.application.manifest import Manifest
from dossier.application.run import RunInputs, execute
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.ledger import Ledger

PIPELINE = "incident-audit"
SOURCE = "incidents-manual"
STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
MODEL = "anthropic:claude-sonnet-4-5-20250929"

# Configuration and verified answers: inputs, committed to git, and not
# recoverable by re-running anything (row 4).
INPUTS = ("sources.yaml", "pipelines", "inbox")


def cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def files(workspace: Path) -> dict[str, bytes]:
    """Every file in the workspace, by workspace-relative path."""
    return {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def held(workspace: Path) -> dict[str, str]:
    """What the ledger holds after a sync: each document at its own snapshot."""
    with Ledger(workspace) as ledger:
        return {row.key: row.snapshot for row in ledger.rows(SOURCE)}


def run(workspace: Path, run_id: str) -> Manifest:
    """One run over what is held, and the manifest it wrote."""
    documents = held(workspace)
    config = PipelineConfig(
        name=PIPELINE,
        sources=[SOURCE],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/01_extract.md",
                input="documents",
                mode="per_file",
            )
        ],
    )
    execute(
        RunInputs(
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            schemas={"extract": None},
            prompts={"extract": prompt_for(["documents"])},
            documents=documents,
            document_text={key: f"# {key}\n\nAs held.\n" for key in documents},
        ),
        workspace=workspace,
        model=FakeModelClient(responses=[f"Reviewed {key}." for key in sorted(documents)]),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )
    return Manifest.read(workspace / "runs" / run_id / "manifest.json")


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """The fixture folder source, held after one real `dossier sync`."""
    write_pipeline(workspace)
    result = cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output
    return workspace


class TestWorkspaceLayoutSeparatesStateFromOutput:
    """R0.8 — generated state under `.dossier/`, run outputs under `runs/`."""

    def test_a_sync_writes_nothing_outside_dossier(self, workspace: Path, monkeypatch):
        """Example 1: the one where a completed sync leaves the workspace alone.

        Snapshots and the ledger are machine-local state, so every path a sync
        creates is under `.dossier/`. Anything else would make deleting that
        directory unsafe, which is the whole split.
        """
        write_pipeline(workspace)
        before = set(files(workspace))

        result = cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        written = set(files(workspace)) - before
        assert written, "the sync stored something"
        assert all(path.startswith(".dossier/") for path in written), sorted(written)
        assert (workspace / ".dossier" / "ledger.db").is_file()
        assert any(path.startswith(".dossier/snapshots/") for path in written)

    def test_a_run_writes_its_manifest_where_a_person_reads_it(self, synced: Path):
        """Example 2: the one where a completed run puts its manifest under `runs/`.

        Not hidden, and outside `.dossier/`: a person opens this file, and
        deleting regenerable state must never take it with it. Whether a
        workspace commits it is that workspace's own choice.
        """
        run_id = "20260806T142203Z-4f1a"

        manifest = run(synced, run_id)

        path = synced / "runs" / run_id / "manifest.json"
        assert path.is_file()
        assert manifest.run_id == run_id
        assert not any(part.startswith(".") for part in path.relative_to(synced).parts)

    def test_deleting_generated_state_costs_only_the_time_to_rebuild_it(
        self, synced: Path, monkeypatch
    ):
        """Example 3: the one where `.dossier/` is deleted and everything comes back.

        Re-synced and re-run, the plan is byte-identical and so are the stage
        artifacts. Only the time taken differs (R5.9) -- and the second run's
        own id, which is what a manifest records about *when* rather than what.
        """
        first = run(synced, "20260806T142203Z-4f1a")
        artifacts = {
            path.name: path.read_bytes()
            for path in sorted((synced / ".dossier" / "cache" / "stage").rglob("*"))
            if path.is_file() and not path.name.endswith(".meta.json")
        }

        shutil.rmtree(synced / ".dossier")
        assert cli(synced, monkeypatch, "sync", PIPELINE).exit_code == 0

        second = run(synced, "20260907T090000Z-bbbb")

        assert second.plan.model_dump_json() == first.plan.model_dump_json()
        rebuilt = {
            path.name: path.read_bytes()
            for path in sorted((synced / ".dossier" / "cache" / "stage").rglob("*"))
            if path.is_file() and not path.name.endswith(".meta.json")
        }
        assert rebuilt == artifacts

    def test_the_inputs_are_never_written_by_a_run(self, synced: Path, monkeypatch):
        """Counter-example (row 4): the one about `sources.yaml` and `pipelines/`.

        Configuration and verified answers are inputs, committed to git, and
        deleting them is not recoverable -- so nothing dossier does writes to
        them. Deleting `.dossier/` does not touch them either.
        """
        before = {
            path: payload for path, payload in files(synced).items() if path.startswith(INPUTS)
        }
        assert before, "the workspace holds its configuration"

        run(synced, "20260806T142203Z-4f1a")
        shutil.rmtree(synced / ".dossier")

        after = {
            path: payload for path, payload in files(synced).items() if path.startswith(INPUTS)
        }
        assert after == before
