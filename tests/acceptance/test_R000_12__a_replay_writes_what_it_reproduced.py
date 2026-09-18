"""R0.12 — `--replay` writes the reproduced artifacts to a new directory under the
run, and writes nothing if any one of them cannot be reproduced.

`runs/<run_id>/replays/<replay_id>/<step>/<document>.json`, named as R0.11 names
them, with the provenance records beside them. What the original run wrote is
never touched: a replay is evidence that the run still reproduces, and evidence
that overwrote what it was checking would be worth less.

All or nothing, because a partial tree would be the substitution R4.7 row 4
forbids. Through the CLI, because a replay is something a person runs, and the
claim is about what they find on disk afterwards.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
DOCUMENTS = ("INC-4821.md", "INC-4822.md", "audit-note.md")


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _answer(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "summary",
                    "value": "reviewed",
                    "source": {"document": document, "span": "Reopened"},
                }
            ],
        }
    )


def _use(monkeypatch, client) -> None:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under `root`, by relative posix path."""
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _cached(workspace: Path) -> dict[tuple[str, str], tuple[bytes, bytes]]:
    """Every stage cache entry, keyed by (step, document): (artifact, record)."""
    root = workspace / ".dossier" / "cache" / "stage"
    entries = {}
    for record in sorted(root.rglob("*.meta.json")):
        meta = json.loads(record.read_text(encoding="utf-8"))
        document = meta["inputs"][0]["path"].split("/", 1)[1]
        artifact = record.with_name(record.name.removesuffix(".meta.json"))
        entries[(meta["step"], document)] = (artifact.read_bytes(), record.read_bytes())
    return entries


def _replays(run: Path) -> list[Path]:
    replays = run / "replays"
    return sorted(replays.iterdir()) if replays.is_dir() else []


def _the_runs_own(run: Path) -> dict[str, bytes]:
    """What the run itself wrote: everything under it except `replays/`."""
    return {name: data for name, data in _tree(run).items() if not name.startswith("replays/")}


def _replay(workspace: Path, monkeypatch, run: Path):
    """A replay with a client that fails on any call: a replay asks no model (R4.7)."""
    from tests.fakes import NoModelClient

    _use(monkeypatch, NoModelClient())
    return _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{run.name}")


@pytest.fixture
def completed(workspace: Path, monkeypatch) -> Path:
    """One finished run, and its directory under `runs/`."""
    from tests.fakes import FakeModelClient

    write_pipeline(workspace, steps=["extract"])
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
    _use(monkeypatch, FakeModelClient(responses=[_answer(key) for key in DOCUMENTS]))
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    (run,) = (workspace / "runs").iterdir()
    return run


class TestAReplayWritesWhatItReproduced:
    """R0.12 — a new directory under the run, or nothing at all."""

    def test_a_run_directory_holding_only_its_manifest_gets_its_outputs_back(
        self, workspace: Path, monkeypatch, completed: Path
    ):
        """Example 1: the one where a run from before R0.11 has nothing to open.

        `extract/` is removed so the directory holds only `manifest.json`, as
        every run did before artifacts were written there. The replay puts
        them under `replays/<replay_id>/`, byte-identical to the cache, and
        says where.
        """
        import shutil

        shutil.rmtree(completed / "extract")
        assert [path.name for path in completed.iterdir()] == ["manifest.json"]

        result = _replay(workspace, monkeypatch, completed)

        assert result.exit_code == 0, result.output
        (replay,) = _replays(completed)
        cached = _cached(workspace)
        for document in DOCUMENTS:
            artifact, record = cached[("extract", document)]
            assert (replay / "extract" / f"{document}.json").read_bytes() == artifact
            assert (replay / "extract" / f"{document}.meta.json").read_bytes() == record
        relative = replay.relative_to(workspace).as_posix()
        assert result.output.rstrip().endswith(
            f"3 artifact(s) reproduced · no model calls · written to {relative}/"
        ), result.output

    def test_two_replays_are_two_identical_directories(
        self, workspace: Path, monkeypatch, completed: Path
    ):
        """Example 2: the one where the same run is replayed twice (R4.7)."""
        assert _replay(workspace, monkeypatch, completed).exit_code == 0
        assert _replay(workspace, monkeypatch, completed).exit_code == 0

        first, second = _replays(completed)
        assert first != second
        assert _tree(first) == _tree(second)
        assert _tree(first), "a replay directory holds the artifacts"

    def test_what_the_run_wrote_is_never_touched(
        self, workspace: Path, monkeypatch, completed: Path
    ):
        """Example 3: the one where a reviewer edited a file under the run.

        The edit stays. The replay directory holds the cache bytes, which is
        what makes the two comparable: evidence that overwrote what it was
        checking would be worth less.
        """
        edited = completed / "extract" / "INC-4821.md.json"
        edited.write_bytes(b'{"document": "INC-4821.md", "fields": [], "note": "edited"}')
        before = _the_runs_own(completed)

        result = _replay(workspace, monkeypatch, completed)

        assert result.exit_code == 0, result.output
        assert _the_runs_own(completed) == before, "the replay changed what the run wrote"
        (replay,) = _replays(completed)
        artifact, _ = _cached(workspace)[("extract", "INC-4821.md")]
        assert (replay / "extract" / "INC-4821.md.json").read_bytes() == artifact

    def test_one_missing_artifact_means_nothing_is_written(
        self, workspace: Path, monkeypatch, completed: Path
    ):
        """Counter-example (row 4): the one where the cache lost one entry.

        `INC-4822`'s entry is gone and the other two are present. Exit 2 with
        the R4.7 row 4 error, and no `replays/` directory at all: three of four
        rematerialised beside a manifest pinning four would read as a complete
        run to anyone who did not see the error.
        """
        root = workspace / ".dossier" / "cache" / "stage"
        removed = 0
        for record in list(root.rglob("*.meta.json")):
            meta = json.loads(record.read_text(encoding="utf-8"))
            if meta["inputs"][0]["path"].endswith("/INC-4822.md"):
                record.with_name(record.name.removesuffix(".meta.json")).unlink()
                record.unlink()
                removed += 1
        assert removed == 1

        result = _replay(workspace, monkeypatch, completed)

        assert result.exit_code == 2
        assert "no cached artifact for 'INC-4822.md'" in result.output
        assert "nothing has been substituted" in result.output
        assert not (completed / "replays").exists()

    def test_eval_reads_a_run_and_leaves_its_directory_alone(
        self, workspace: Path, monkeypatch, completed: Path
    ):
        """Counter-example (row 5): the one where `eval` reproduces through the same path.

        `dossier eval` scores the latest run by reproducing it from the cache,
        as a replay does. It writes nothing under `runs/`: eval reads a run, it
        does not add to one.
        """
        from tests.fakes import NoModelClient

        _use(monkeypatch, NoModelClient())
        before = _tree(workspace / "runs")

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        assert result.exit_code == 0, result.output
        assert _tree(workspace / "runs") == before
        assert not (completed / "replays").exists()
