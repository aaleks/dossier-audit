"""R13.4 - a version id reaches a tag, a link and the terminal, and nothing else.

R12.4 makes this promise for a dataset id. It is restated for the version id and
tested separately, because of *when* this one arrives: a dataset is published by
a command whose only output is the record, while a version is registered during
`dossier run` -- the command R10.4 is about.

So the test is the one R10.4 makes: run the same pipeline with the registry on
and with it off, and diff every byte the run wrote. A server-assigned id that
reached a cache key would make a run's result depend on whether a server
happened to be up, and a cache hit would stop meaning that nothing relevant
changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.fakes import FakeTracker, FakeVersionRegistry, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _workspace(root: Path, monkeypatch) -> Path:
    (root / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(root, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(root, monkeypatch, "sync", PIPELINE).exit_code == 0
    return root


def _written(workspace: Path, run_id: str) -> dict[str, str]:
    """Every artifact this run wrote, by path, hashed.

    `manifest.json` is compared separately: it holds the run id and the start
    time, the only two things about a run that R4.8 allows to differ between two
    runs of one plan. Everything else here must be byte-identical.
    """
    directory = workspace / "runs" / run_id
    return {
        str(path.relative_to(directory)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def _plan(workspace: Path, run_id: str) -> dict:
    """The resolved plan the manifest holds -- what R4.8 says is identical."""
    manifest = workspace / "runs" / run_id / "manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8"))["plan"]


def _cache_keys(workspace: Path) -> set[str]:
    """Every stage cache key this workspace holds."""
    stage = workspace / ".dossier" / "cache" / "stage"
    return {path.name for path in stage.rglob("*") if path.is_file()}


def _run(workspace: Path, monkeypatch) -> str:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return result.output.split("run ", 1)[1].split(" ", 1)[0].strip()


class TestAVersionIdReachesNothingOnDisk:
    """R13.4 - the id is printed and linked; it is never written down."""

    def test_the_same_run_writes_the_same_bytes_with_and_without_a_registry(
        self, workspace: Path, monkeypatch
    ):
        """Example 1: the one R10.4 already makes for tracking as a whole.

        Registered second rather than first, so that if the id leaked into a
        key the second run would miss the cache the first filled -- which is
        the consequence, not just the symptom.
        """
        root = _workspace(workspace, monkeypatch)

        untracked = _run(root, monkeypatch)
        keys_before = _cache_keys(root)

        import dossier.cli.bootstrap as cli

        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: FakeTracker(), raising=False)
        registry = FakeVersionRegistry()
        monkeypatch.setattr(
            cli, "build_version_registry", lambda settings: registry, raising=False
        )
        tracked = _run(root, monkeypatch)

        assert registry.versions, "the registry was asked; otherwise this proves nothing"
        assert _cache_keys(root) == keys_before, "a version id reached a cache key"
        # Every artifact byte-identical, and the resolved plan with it. The run
        # id and the start time are the only two things R4.8 lets differ, and
        # they are why the manifest is compared through its plan.
        assert _written(root, tracked) == _written(root, untracked)
        assert _plan(root, tracked) == _plan(root, untracked)

    def test_the_id_appears_in_no_file_the_run_wrote(self, workspace: Path, monkeypatch):
        """Example 2: the one where the id is searched for by name.

        Not a diff this time but a search: a value can be equal across two runs
        and still be written down -- if both runs got the same id back. This is
        the assertion that catches that.
        """
        import dossier.cli.bootstrap as cli

        root = _workspace(workspace, monkeypatch)
        registry = FakeVersionRegistry()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: FakeTracker(), raising=False)
        monkeypatch.setattr(
            cli, "build_version_registry", lambda settings: registry, raising=False
        )

        _run(root, monkeypatch)

        assert registry.versions
        version_id = registry.versions[0].version_id
        for path in sorted(root.rglob("*")):
            if path.is_file():
                assert version_id not in path.read_bytes().decode("utf-8", "replace"), path
